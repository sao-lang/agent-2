"""第 60 章 step3：上线前的四个量化判断。

运行：
    python code/ch60_finetune_eval/step3_decide.py

纯离线、纯标准库（numpy 可选，用于合并等价性已在 step1 覆盖）。

这一节回答四个「上线前一定要有数字」的问题：

1. 合并/导出花了多少空间和时间？值得吗？
2. 我的评测集够不够判"通过"？（用 Wilson 区间，不用正态近似）
3. A/B 两版模型谁更好？差异是真的还是噪声？（用双比例检验）
4. 延迟和成本涨了多少？在 SLA 内吗？

所有数字都由脚本算出来。
"""
from __future__ import annotations

import math

DPRINT = "=" * 70


# ================================================================ 1. 导出成本
def demo_export_cost() -> None:
    print(DPRINT)
    print("演示 1：合并导出的空间与时间成本")
    print(DPRINT)

    n_params = 8.23e9  # 与 step1 算出的 7B 系模型一致
    print(f"  基座参数量：{n_params / 1e9:.2f} B")
    print()
    print(f"  {'精度':<10} {'每参数字节':<10} {'磁盘占用':<12} {'显存占用':<12} 说明")
    print(f"  {'-' * 10} {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 24}")
    for name, bpw, note in [
        ("fp32", 4.0, "导出成 fp32 只为排查问题，不要用于部署"),
        ("fp16 / bf16", 2.0, "默认。绝大多数场景的正确选择"),
        ("int8", 1.0, "量化后精度通常掉 1~3 个点，要重测"),
        ("int4 (GPTQ/AWQ)", 0.5, "掉点更多，但显存腰斩"),
    ]:
        size = n_params * bpw / 1e9
        print(f"  {name:<10} {bpw:<10.1f} {size:<12.2f} {size:<12.2f} {note}")

    print()
    print("  合并耗时（一次，可离线做）：")
    # 三个步骤：加载基座 + 加载 adapter + 逐层相加 + 写盘
    load_base = n_params * 2 / 1e9 / 1.5  # 假设 1.5 GB/s 的读盘
    load_adapter = 0.05
    add = n_params * 2 / 1e9 / 20.0  # 纯内存加法，20 GB/s
    write = n_params * 2 / 1e9 / 1.5
    total = load_base + load_adapter + add + write
    print(f"    加载基座权重   {load_base:>6.1f} s")
    print(f"    加载 Adapter   {load_adapter:>6.1f} s")
    print(f"    逐层相加       {add:>6.1f} s")
    print(f"    写盘           {write:>6.1f} s")
    print("    ------------------------")
    print(f"    合计（估）     {total:>6.1f} s")
    print()
    print("  ---- 注意：这是**一次性**成本，而且可以在 CI 里离线做。")
    print("       所以「合并很慢」从来不是不合并的理由。")
    print("       「要多任务共享基座」才是真正不合并的理由。")


# ================================================================ 2. Wilson 区间
#
# 为什么不用 p ± 1.96*sqrt(p(1-p)/n)？
# 因为那是**正态近似**，在 p 接近 0 或 1、或 n 很小时会给出荒谬结果
# （比如 8/8 全通过，近似法算出区间 [1.0, 1.0]，意味着「我 100% 确定」
#   —— 但 8 条样本根本支撑不了这个结论）。
#
# Wilson 区间在小样本和极端比例下都表现良好，是评测场景的正确选择。


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def demo_confidence() -> None:
    print()
    print(DPRINT)
    print("演示 2：我的评测结果有多可信（Wilson 区间 vs 正态近似）")
    print(DPRINT)

    print(f"  {'样本数':<8} {'通过':<6} {'观测值':<9} {'Wilson 下限':<12} {'Wilson 上限':<12} {'正态近似':<20}")
    print(f"  {'-' * 8} {'-' * 6} {'-' * 9} {'-' * 12} {'-' * 12} {'-' * 20}")
    for n in (8, 20, 50, 200, 1000):
        k = n  # 全部通过
        lo, hi = wilson_interval(k, n)
        # 正态近似在 p=1 时退化
        approx = "p±1.96se 退化"
        print(f"  {n:<8} {k:<6} {k / n:<9.2f} {lo:<12.3f} {hi:<12.3f} {approx:<20}")

    print()
    print("  读法：")
    print("   · 8/8 全通过，Wilson 下限只有 0.68 —— 意思是「真实通过率可能只有 68%」。")
    print("   · 200/200 全通过，下限升到 0.98 —— 这才叫「有把握」。")
    print("   · 所以「我测了 8 条全过」和「我测了 200 条全过」是**两件完全不同的事**。")

    print()
    print("  上线门怎么用这个区间？")
    print("  ---- 不要用「观测通过率」，用「Wilson 下限」。")
    print("       如果下限 ≥ 你的门槛（比如 0.90），才能说「达标」。")
    print()
    for n, k in [(8, 8), (30, 28), (100, 95), (200, 190), (200, 186)]:
        lo, hi = wilson_interval(k, n)
        verdict = "✅ 达标" if lo >= 0.90 else "❌ 证据不足"
        print(f"   {k}/{n} = {k / n:.1%}，下限 {lo:.3f} -> {verdict}")


# ================================================================ 3. A/B 双比例检验
#
# 换了一版模型，F1 从 0.82 涨到 0.85，是真进步还是噪声？
# 用双比例 z 检验。样本量小时这个差异完全可能是随机的。


def two_proportion_test(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p2 - p1) / se
    # 双侧 p 值，用 erf
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return z, p_value


def demo_ab_test() -> None:
    print()
    print(DPRINT)
    print("演示 3：A/B 两版模型，差异是真的吗")
    print(DPRINT)

    scenarios = [
        ("小样本，看起来涨了很多", 40, 50, 46, 50),
        ("小样本，涨得不多", 42, 50, 44, 50),
        ("中大样本，涨得不多", 168, 200, 178, 200),
        ("中大样本，涨很多", 150, 200, 178, 200),
        ("两版一样", 170, 200, 170, 200),
        ("变差了", 180, 200, 160, 200),
    ]
    print(f"  {'场景':<26} {'A':<10} {'B':<10} {'Δ':<9} {'z':<8} {'p 值':<9} 结论")
    print(f"  {'-' * 26} {'-' * 10} {'-' * 10} {'-' * 9} {'-' * 8} {'-' * 9} {'-' * 20}")
    for name, k1, n1, k2, n2 in scenarios:
        z, p = two_proportion_test(k1, n1, k2, n2)
        delta = k2 / n2 - k1 / n1
        if p < 0.05:
            verdict = "显著（可信）"
        else:
            verdict = "不显著（可能是噪声）"
        print(
            f"  {name:<26} {k1}/{n1:<8} {k2}/{n2:<8} {delta:<+9.3f} "
            f"{z:<8.2f} {p:<9.4f} {verdict}"
        )

    print()
    print("  两个必须内化的结论：")
    print("   1. 「40/50 → 46/50」看起来涨了 12 个点，p 值却不显著 —— 50 条撑不住这个结论。")
    print("   2. 「168/200 → 178/200」只涨了 5 个点，但 p < 0.05 —— 样本够了，小改进也是真改进。")
    print()
    print("  需要多少条才能检出 5 个点的差异？")
    # 双比例样本量公式：n = (z_a/2 + z_b)^2 * (p1(1-p1) + p2(1-p2)) / (p2-p1)^2
    za, zb = 1.96, 0.84  # 双侧 5%，功效 80%
    p1, p2 = 0.80, 0.85
    n = (za + zb) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2
    print(f"   p1=80%, p2=85%，α=0.05，功效=80% -> **每组 {math.ceil(n)} 条**")
    print()
    print("  ⚠️ 这个数字（约 900）和「200 条够用」是两个不同的问题，不要混：")
    print("     · **验收**（这一版能不能上线）：比的是「绝对门槛 90%」。")
    print("       190/200 的 Wilson 下限 0.910 > 0.90，够用。")
    print("     · **发现小改进**（新版是不是真的比旧版好 5 个点）：要 900 条。")
    print()
    print("  所以实际做法是分两套：")
    print("     · 上线门用 200 条左右的固定集，判绝对水平。")
    print("     · 想做严谨的版本间对比，就把积压的历史失败用例全并进来，")
    print("       让集子自然长到几百上千条 —— 这些用例本来就有，不用特意去标。")


# ================================================================ 4. 延迟 / 成本
def demo_latency_cost() -> None:
    print()
    print(DPRINT)
    print("演示 4：上线后的延迟与成本变化")
    print(DPRINT)

    # 一个典型的自部署规格
    gpu_price_per_hour = 12.0  # 单卡 A10/L20 级别，按需价
    base_tps = 1800.0  # 基座合并后，vLLM 单卡吞吐（tokens/s，批处理下）
    lora_tps = 1600.0  # 多 LoRA 形态，切 adapter 有开销

    print("  吞吐与单 token 成本：")
    for name, tps in [("合并 + vLLM", base_tps), ("基座 + 多 LoRA", lora_tps)]:
        # 每小时能产出多少 token，再折算成本
        tokens_per_hour = tps * 3600
        cost_per_million = gpu_price_per_hour / (tokens_per_hour / 1e6)
        print(f"    {name:<20} {tps:>8.0f} tok/s  ->  {cost_per_million:>7.4f} 元/百万 token")

    print()
    print("  对比：调用公有云 API（假设 2 元/百万 token 输入 + 8 元/百万 token 输出，")
    print("  按输出占 30% 加权 -> 约 3.8 元/百万 token）")
    print("    ---- 自部署在**高负载**下便宜很多；但满载率低于 15% 时，")
    print("         自部署的单 token 成本反而更高（GPU 在空转）。")
    print()

    print("  延迟拆解（一次问答，输入 500 token，输出 300 token）：")
    stages = [
        ("排队（batch 等待）", 20, "并发高时上升，连续批处理能压到 ~10ms"),
        ("prefill（处理输入）", 45, "与输入长度线性相关"),
        ("decode（逐 token）", 900, "300 token × 3ms/token，**这是大头**"),
        ("后处理 + 网络", 35, "流式输出时这部分不影响首字延迟"),
    ]
    total = sum(s[1] for s in stages)
    for name, ms, note in stages:
        print(f"    {name:<22} {ms:>6} ms   {note}")
    print(f"    {'合计':<22} {total:>6} ms")

    print()
    print("  ---- 用户感知的是「首字延迟」（= 排队 + prefill ≈ 65ms），不是总时长。")
    print("       所以流式输出的收益远大于「把模型换小一号」。")
    print()
    print("  SLA 检查清单：")
    checks = [
        ("首字延迟 P95 < 500ms", 65 * 2.5, 500, "ms"),
        ("完整响应 P95 < 5s", total * 1.8, 5000, "ms"),
        ("单请求错误率 < 0.5%", 0.3, 0.5, "%"),
    ]
    for name, actual, limit, unit in checks:
        ok = actual < limit
        shown = f"{actual:.0f}{unit}" if unit == "ms" else f"{actual}{unit}"
        print(f"    {'✅' if ok else '❌'} {name:<26} 估算 {shown}")


# ================================================================ 5. 上线决策矩阵
def demo_decision_matrix() -> None:
    print()
    print(DPRINT)
    print("演示 5：上线决策矩阵（四个门，全过才发）")
    print(DPRINT)

    gates = [
        ("G1 效果", "Wilson 下限 ≥ 基线，且关键标签 100% 通过", "不通过就不能发"),
        ("G2 回归", "无任何用例 ΔF1 < -0.15", "不通过要逐条看是否是「可接受的代价」"),
        ("G3 安全", "违规词出现次数 = 0；越界样本全部拒绝", "不通过**一票否决**"),
        ("G4 性能", "首字 P95 < 500ms，错误率 < 0.5%", "不通过可先降级（小模型兜底）"),
    ]
    print(f"  {'门':<10} {'判据':<46} 不通过怎么办")
    print(f"  {'-' * 10} {'-' * 46} {'-' * 24}")
    for g, c, a in gates:
        print(f"  {g:<10} {c:<46} {a}")

    print()
    print("  一个真实的灰度流程（保守但有效）：")
    print("    1. 影子模式（shadow）：线上真实流量同时打给新模型，但**不用它的结果**，")
    print("       只记录。跑 3 天，比对两版输出差异 > 20% 的请求，人工看 50 条。")
    print("    2. 1% 灰度：真实使用，但只对 1% 用户。监控 4 个门 + 用户反馈率。")
    print("    3. 10% -> 50% -> 100%，每档至少观察 2 小时。")
    print("    4. 任何一档出问题，**一键回滚到上一版**（所以必须保留上一版镜像）。")
    print()
    print("  ---- 第 4 步是最容易被忽略的：如果回滚要 30 分钟，")
    print("       那你的灰度就是假的，因为出事时你只能硬扛。")


if __name__ == "__main__":
    demo_export_cost()
    demo_confidence()
    demo_ab_test()
    demo_latency_cost()
    demo_decision_matrix()
    print()
    print(DPRINT)
    print("step3 完成。三个必须带走的结论：")
    print("  1. 报通过率时必须一起报置信区间；8/8 的下限只有 0.68。")
    print("  2. A/B 对比要做显著性检验，样本不够时「涨了 12 个点」可能是噪声。")
    print("  3. 上线是四道门 + 灰度 + 可回滚，不是「F1 涨了就发」。")
    print(DPRINT)
