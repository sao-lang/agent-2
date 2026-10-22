"""第 60 章 step1：合并 / 导出 / 部署前的文件清单。

运行：
    python code/ch60_finetune_eval/step1_merge_export.py

纯离线、纯标准库。这一节回答三个"上线前必须想清楚"的问题：

1. Adapter 不合并，推理时到底慢多少？为什么变慢？
2. 合并之后，产物里到底有哪些文件、各多大？能不能直接上线？
3. "合并后的模型"和"原基座 + Adapter"的输出**是否完全一致**？
   —— 这个问题很多人想当然，实际并不完全一致，本章会给出原因。

所有数字都由脚本算出来，公式写在代码里。
"""
from __future__ import annotations

import json

# ================================================================ 1. 为什么 Adapter 不合并会变慢
#
# LoRA 的前向：
#     y = W x + (alpha/r) * B A x
#
# 不合并时，每一层都要**额外做两次矩阵乘**（A 和 B），
# 并且要在显存里同时保留 W、A、B 三份权重。
#
# 合并后：W' = W + (alpha/r) * B A，前向退回一次矩阵乘。
#
# 关键点：合并是**无损**的（在浮点意义下），因为它只是把两个矩阵加在一起。
# 但注意——"无损"指的是数学等价，浮点累加顺序不同会带来极小的差异。

DPRINT = "=" * 68


def demo_latency_overhead() -> None:
    print(DPRINT)
    print("演示 1：Adapter 不合并的推理开销")
    print(DPRINT)

    # 7B 模型的一个典型线性层：hidden 3584 -> 3584
    hidden = 3584
    rank = 16

    # 一次 y = W x 的乘加次数（每 token）
    flops_base = 2 * hidden * hidden
    # LoRA 额外部分：x -> A(rank x hidden) -> B(hidden x rank)
    flops_lora = 2 * hidden * rank + 2 * rank * hidden

    overhead = flops_lora / flops_base
    print(f"  基座一层 FLOPs/token : {flops_base:>12,}")
    print(f"  LoRA 额外 FLOPs/token: {flops_lora:>12,}")
    print(f"  额外计算占比         : {overhead:>11.2%}")

    print()
    print("  为什么看起来只有一点点，实际却很慢？")
    print("  ---- 因为 LoRA 的那两次小矩阵乘是**无法和主矩阵乘融合**的，")
    print("       每层都要多启动 kernel 幂。7B/28 层 = 每 token 多 28 * 2 = 56 次 kernel launch。")
    print("       小矩阵乘的 GPU 利用率很低（rank=16 太小，吃不满 SM），实际耗时远大于 FLOPs 占比。")

    print()
    print("  另一个隐藏成本：显存。")
    # bf16 每参数 2 字节
    base_bytes = hidden * hidden * 2
    lora_bytes = 2 * rank * hidden * 2
    print(f"  基座一层权重   : {base_bytes / 1024 / 1024:>6.2f} MiB")
    print(f"  LoRA 一层权重  : {lora_bytes / 1024:>6.2f} KiB  (占 {lora_bytes / base_bytes:.3%})")
    print("  ---- 显存侧几乎没成本，成本全在「kernel 幂」和「无法融合」上。")

    print()
    print("  结论：")
    print("   · 只做单机调试 -> 不合并也行，改代码方便")
    print("   · 要走推理服务（vLLM / TGI / 线上）-> **必须合并**")
    print("   · 要同时服务多个 Adapter（同一基座不同任务）-> 反而不要合并，")
    print("     用多 LoRA 加载（vLLM 的 --enable-lora），共享一份基座权重")


# ================================================================ 2. 产物文件清单
#
# 这一段是"上线前对着文件列表检查一遍"用的清单。
# 每一项都对应一个真实会踩的坑。


def demo_artifact_inventory() -> None:
    print()
    print(DPRINT)
    print("演示 2：合并导出的产物清单（以及每项的实际作用）")
    print(DPRINT)

    # 7B 模型，hidden 3584，28 层，词表 152064
    n_layers = 28
    hidden = 3584
    vocab = 152064
    # 中间层 FFN 大小，LLaMA 系一般是 hidden * 3.5 取整
    inter = 18944
    # 每层参数量（注意力 4 个投影 + MLP 3 个投影）
    attn = 4 * hidden * hidden
    mlp = 3 * hidden * inter
    per_layer = attn + mlp
    # embedding 和 lm_head（不 tie 的情况下是两份）
    embed = vocab * hidden
    total = n_layers * per_layer + 2 * embed

    print(f"  基座参数量：{total / 1e9:.2f} B")
    print(f"    其中 每层 {per_layer / 1e9:.3f} B × {n_layers} 层 = {n_layers * per_layer / 1e9:.2f} B")
    print(f"    其中 embedding + lm_head = {2 * embed / 1e9:.2f} B  (占 {2 * embed / total:.1%})")
    print("    ---- 词表占了近 1/3 参数，所以「词表大小」会显著影响显存。")

    print()
    files = [
        ("config.json", "模型结构定义（层数/维度/激活函数）", "必须", "少了这个，vLLM 不知道模型长什么样"),
        ("generation_config.json", "默认采样参数（temperature/top_p/eos）", "强烈建议", "缺了会跳过你训练时用的 stop token"),
        ("tokenizer.json", "完整分词器（词表 + 合并规则）", "必须", "只给 vocab.txt 不够，BPE 规则会丢"),
        ("tokenizer_config.json", "分词器配置（chat_template 也常在这里）", "必须", "chat_template 缺了，对话格式就错了"),
        ("special_tokens_map.json", "pad/eos/bos 的映射关系", "必须", "缺了 pad token 会被当成 unk"),
        ("model.safetensors (或 index)", "权重本体", "必须", "分片时必须有 index，否则拼不起来"),
        ("chat_template.jinja", "对话模板单独成文件", "视情况", "新版 transformers 支持，便于热更新"),
    ]
    print(f"  {'文件':<28} {'大小量级':<12} {'必须?':<10} 作用 / 缺了会怎样")
    print(f"  {'-' * 28} {'-' * 12} {'-' * 10} {'-' * 34}")
    weight_bytes = total * 2  # bf16
    for name, desc, need, why in files:
        if "safetensors" in name:
            size = f"{weight_bytes / 1e9:.1f} GB"
        elif name == "tokenizer.json":
            size = f"{vocab * 30 / 1e6:.0f} MB"
        elif name.startswith("config"):
            size = "~1 KB"
        else:
            size = "~2 KB"
        print(f"  {name:<28} {size:<12} {need:<10} {desc}")

    print()
    print("  合并后的真实目录结构（走 safetensors 分片）：")
    print("""
    merged-model/
      config.json
      generation_config.json
      model-00001-of-00004.safetensors    <- 每片 ~4 GB
      model-00002-of-00004.safetensors
      model-00003-of-00004.safetensors
      model-00004-of-00004.safetensors
      model.safetensors.index.json         <- 分片索引，缺了加载不了
      special_tokens_map.json
      tokenizer.json
      tokenizer_config.json
    """)

    print("  ⚠️ 三个最常漏的文件：")
    print("     1. generation_config.json —— 少了它，eos_token_id 会退回默认值，")
    print("        你的模型可能永远不停止（生成到 max_tokens 为止）。")
    print("     2. model.safetensors.index.json —— 分片模型少了它，")
    print("        from_pretrained 会报 KeyError 而不是「文件缺失」，很难定位。")
    print("     3. tokenizer_config.json 里的 chat_template —— 少了它，")
    print("        推理时不会套模板，模型看到的是裸文本，效果断崖式下跌。")


# ================================================================ 3. 合并真的无损吗
#
# 数学上等价，浮点上不等价。这一段量化这个差异。
# 用 numpy 手工模拟（不需要 torch）：随机生成 W, A, B，比较两种前向。


def demo_merge_equivalence() -> None:
    print()
    print(DPRINT)
    print("演示 3：合并后的输出和「基座 + Adapter」一致吗？")
    print(DPRINT)

    try:
        import numpy as np
    except ImportError:
        print("  需要 numpy 才能跑这个演示：pip install numpy")
        return

    rng = np.random.default_rng(0)
    d, r = 256, 16
    alpha = 32.0
    scale = alpha / r

    # 基座权重（bf16 量级，标准差 ~0.02）
    W = rng.normal(0, 0.02, (d, d)).astype(np.float32)
    # LoRA 初始化：A 高斯，B 全零（这是标准初始化，训练开始时增量为 0）
    A = rng.normal(0, 0.02, (r, d)).astype(np.float32)
    B = rng.normal(0, 0.01, (d, r)).astype(np.float32)
    x = rng.normal(0, 1, (d, 1)).astype(np.float32)

    # 路径 1：不合并，分开算
    y_lora = W @ x + scale * (B @ (A @ x))
    # 路径 2：先合并权重，再算
    W_merged = W + scale * (B @ A)
    y_merged = W_merged @ x

    diff = np.abs(y_lora - y_merged)
    denom = np.abs(y_lora).mean()
    print(f"  输出维度           : {d}")
    print(f"  输出 L2 范数       : {np.linalg.norm(y_lora):.6f}")
    print(f"  最大绝对误差       : {diff.max():.3e}")
    print(f"  相对误差（对均值） : {diff.mean() / denom:.3e}")

    print()
    print("  这个误差来自哪里？")
    print("  ---- 两条路径的**浮点累加顺序**不同：")
    print("       路径 1 是 (B(A x))，先降维到 rank 再升维；")
    print("       路径 2 是 (W + BA)x，先在 fp32 里把两个矩阵加起来，再做一次乘。")
    print("       加法顺序不同 -> 舍入误差不同 -> 结果在 1e-7 量级上不同。")

    print()
    print("  这个差异重要吗？")
    print("  ---- **单次前向不重要，但会放大。**")
    # 模拟层叠放大：28 层，每层都有同量级的相对误差
    per_layer_rel = diff.mean() / denom
    layers = 28
    # 误差不是简单相加，但上界是线性增长；这里给线性上界
    print(f"  单层相对误差 {per_layer_rel:.2e} × 28 层 ≈ {per_layer_rel * layers:.2e}（上界）")
    print("  ---- 仍在 1e-6 以内，对生成结果几乎无影响（贪心解码可能偶发换一个 token）。")
    print()
    print("  真正的「不一致」不是浮点误差，而是下面这三种：")
    print("   1. 合并时忘了 scale（alpha/r）—— 这是**数量级**的错误，输出全乱")
    print("   2. 只合并了一部分层（target_modules 记错）—— 有的层有增量、有的没有")
    print("   3. 合并后没更新 config.json 的 quantization_config —— 用 fp16 加载了一个")
    print("      本该 4bit 的模型，或者反过来")


# ================================================================ 4. 部署形态选择
def demo_deploy_shape() -> None:
    print()
    print(DPRINT)
    print("演示 4：三种部署形态，怎么选")
    print(DPRINT)

    rows = [
        ("合并 + vLLM", "1 个模型", "最高（PagedAttention + 连续批处理）", "只服务一个任务"),
        ("基座 + 多 LoRA", "N 个 Adapter 共享 1 份基座", "略低（每请求要切 LoRA）", "同一基座多任务 / 多租户"),
        ("基座 + Adapter（transformers）", "1 个", "最低（无批处理优化）", "调试 / 离线批量"),
    ]
    print(f"  {'形态':<30} {'内存占用':<24} {'吞吐':<32} 适用")
    print(f"  {'-' * 30} {'-' * 24} {'-' * 32} {'-' * 20}")
    for a, b, c, d in rows:
        print(f"  {a:<30} {b:<24} {c:<32} {d}")

    print()
    print("  判据（按顺序问自己）：")
    print("   1. 只有一个任务？ -> 合并 + vLLM，不做第二个选择")
    print("   2. 多个任务但基座相同？ -> 多 LoRA 加载，省 N-1 份基座显存")
    print("   3. 基座不同？ -> 各起各的服务，不要硬塞进一个进程")
    print()
    print("  一个常见的错判：")
    print("   「我有 5 个客户，每个客户一个 LoRA，所以起 5 个 vLLM 实例」")
    print("   -> 5 × 14 GB = 70 GB，其实用 --enable-lora 只要 14 GB + 5 × 几十 MB。")


def demo_vllm_request() -> None:
    print()
    print(DPRINT)
    print("演示 5：vLLM 的 OpenAI 兼容接口长什么样（请求体）")
    print(DPRINT)

    body = {
        "model": "merged-model",
        "messages": [
            {"role": "system", "content": "你是一个严谨的技术助手。"},
            {"role": "user", "content": "LoRA 的 alpha 有什么用？"},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
        "stop": ["<|im_end|>"],
        "extra_body": {"repetition_penalty": 1.05},
    }
    print("  POST http://localhost:8000/v1/chat/completions")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    print()
    print("  四个容易踩的点：")
    print("   · temperature 设 0 才是贪心解码；设 0.0001 仍是采样，结果不稳定。")
    print("   · stop 要写你训练时用的真实结束符。写成 \"<|endoftext|>\" 但训练用的是")
    print("     \"<|im_end|>\"，模型不会停 -> 输出到 max_tokens 截断。")
    print("   · vLLM 的 repetition_penalty 要走 extra_body，不在标准 OpenAI 字段里。")
    print("   · messages 里的 system 会被 chat_template 包起来；如果你的模板没有")
    print("     system 分支，system 内容会被静默丢弃 —— 这是最常见的「上线后效果变差」原因。")


if __name__ == "__main__":
    demo_latency_overhead()
    demo_artifact_inventory()
    demo_merge_equivalence()
    demo_deploy_shape()
    demo_vllm_request()
    print()
    print(DPRINT)
    print("step1 完成。三个必须带走的结论：")
    print("  1. 要上推理服务就合并；要多任务共享基座就不合并（用多 LoRA）。")
    print("  2. 合并产物里 generation_config / index.json / chat_template 最容易漏。")
    print("  3. 合并的「不一致」主要不是浮点误差，而是漏了 scale / 漏了层 / 漏了量化配置。")
    print(DPRINT)
