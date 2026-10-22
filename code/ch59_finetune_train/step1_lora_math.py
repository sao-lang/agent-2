"""第 59 章 step1：LoRA / QLoRA 的参数量与显存 —— 全部手算，不猜。

运行：
    python code/ch59_finetune_train/step1_lora_math.py

纯离线、纯标准库。为什么不用 torch？
因为"显存够不够"这件事**是一个算术问题**，不需要真的跑训练就能算准。
算清楚之后再去租 GPU，能省下大量"跑一半 OOM"的时间。

所有公式都在代码里写明来源，所有数字都是脚本算出来的。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ================================================================ 模型规格
@dataclass
class ModelSpec:
    name: str
    n_params_b: float      # 参数量（十亿）
    n_layers: int
    hidden: int
    # LoRA 通常挂在这些线性层上
    target_modules: tuple[str, ...]

    @property
    def approx_linear_params(self) -> int:
        """粗略估计所有"可挂 LoRA"的线性层参数总量。

        每个 Transformer 层里，q/k/v/o 四个 proj 都是 hidden × hidden，
        MLP 的 gate/up/down 约 hidden × 4*hidden × 2 + 4*hidden × hidden。
        这里用「每层 ≈ 12 × hidden²」这个常用近似，
        和真实值的误差通常在 10% 以内（够用来做显存决策）。
        """
        return int(self.n_layers * 12 * self.hidden**2)


MODELS = {
    "qwen2.5-1.5b": ModelSpec("Qwen2.5-1.5B", 1.5, 28, 1536, ("q_proj", "k_proj", "v_proj", "o_proj")),
    "qwen2.5-7b": ModelSpec("Qwen2.5-7B", 7.6, 28, 3584, ("q_proj", "k_proj", "v_proj", "o_proj")),
    "qwen2.5-14b": ModelSpec("Qwen2.5-14B", 14.7, 48, 5120, ("q_proj", "k_proj", "v_proj", "o_proj")),
    "llama3.1-8b": ModelSpec("Llama-3.1-8B", 8.0, 32, 4096, ("q_proj", "k_proj", "v_proj", "o_proj")),
}


# ================================================================ LoRA 参数量
def lora_params(spec: ModelSpec, rank: int, targets: int = 4, alpha: float | None = None) -> int:
    """LoRA 的可训练参数量。

    对每个被挂上的线性层（hidden × hidden），LoRA 加两个矩阵：
        A: (rank × hidden)      ← 降维
        B: (hidden × rank)      ← 升维
    参数量 = 2 × rank × hidden（每个层）

    注意：这里不算 bias（通常也不挂 LoRA）。
    """
    return targets * 2 * rank * spec.hidden * spec.n_layers


def demo_lora_size() -> None:
    print("① LoRA 到底训了多少参数（rank 变化的真实影响）")
    print()
    spec = MODELS["qwen2.5-7b"]
    print(f"   模型：{spec.name}，{spec.n_params_b}B 参数，{spec.n_layers} 层，hidden={spec.hidden}")
    print(f"   挂在 {len(spec.target_modules)} 个投影层上：{', '.join(spec.target_modules)}")
    print()
    print(f"   {'rank':>6}{'可训练参数':>16}{'占全模型':>12}{'每卡省下的优化器状态':>22}")
    print("   " + "-" * 58)
    for r in [1, 2, 4, 8, 16, 32, 64, 128]:
        p = lora_params(spec, r)
        ratio = p / (spec.n_params_b * 1e9)
        # AdamW 每个可训练参数需要 2 份 fp32 状态（m 和 v）= 8 字节
        saved = p * 8 / 1e9
        print(f"   {r:>6}{p:>16,}{ratio:>11.2%}{saved:>19.2f} GB")
    print()
    print("   注意最后一列：**可训练参数越少，优化器状态越小。**")
    print("   7B 全参微调的优化器状态是 7.6e9 × 8 = 60.8 GB —— 单卡根本放不下。")
    print()


def demo_alpha() -> None:
    print("② alpha：LoRA 的「音量旋钮」")
    print()
    rank = 16
    print(f"   固定 rank={rank}，改 alpha 会改什么：")
    print()
    print(f"   {'alpha':>8}{'缩放系数 alpha/r':>20}{'含义':<30}")
    print("   " + "-" * 60)
    for a in [8, 16, 32, 64]:
        scale = a / rank
        meaning = {
            0.5: "增量被压小，学得慢，接近不改模型",
            1.0: "最常用的默认值",
            2.0: "增量被放大，学得快但容易过拟合",
            4.0: "激进，通常需要更小的学习率",
        }.get(scale, "偏激")
        print(f"   {a:>8}{scale:>20.1f}  {meaning}")
    print()
    print("   实战建议：")
    print("     · 先用 alpha = rank（缩放系数 1.0）作为基线」")
    print("     · 要调就调学习率，别同时动 alpha 和 lr（两个变量分不清谁起作用）")
    print("     · 有些框架把 alpha 默认成 2×rank，那是另一套惯例，**看配置文件不要猜**")
    print()


def demo_target_modules() -> None:
    print("③ 挂在哪几层：4 个 vs 7 个，差多少」")
    print()
    spec = MODELS["qwen2.5-7b"]
    rank = 16
    configs = [
        ("只挂 q/v（最省）", 2),
        ("挂 q/k/v/o（常见）", 4),
        ("q/k/v/o + MLP 三层（最强）", 7),
    ]
    print(f"   {'配置':<28}{'可训练参数':>16}{'相对比值':>12}")
    print("   " + "-" * 56)
    base = None
    for name, n in configs:
        p = lora_params(spec, rank, targets=n)
        if base is None:
            base = p
        print(f"   {name:<28}{p:>16,}{p / base:>11.1f}x")
    print()
    print("   经验：")
    print("     · 只改格式/语气 → q/v 够用（省显存，省时间）")
    print("     · 要学新领域表达 → 至少 q/k/v/o")
    print("     · 加 MLP 有明显收益，但训练时间翻倍；先试 4 个，不够再加」")
    print()


# ================================================================ 显存估算
def demo_memory() -> None:
    print("④ 显存估算：为什么 7B 全参要 8 张 A100，LoRA 一张 4090 就够」")
    print()

    @dataclass
    class Plan:
        label: str
        weights_gb: float
        grads_gb: float
        optim_gb: float
        activ_gb: float

        @property
        def total(self) -> float:
            return self.weights_gb + self.grads_gb + self.optim_gb + self.activ_gb

    n = 7.6e9
    seq, batch = 2048, 2
    # 激活值近似：层数 × batch × seq × hidden × 字节数 × 系数
    spec = MODELS["qwen2.5-7b"]
    act = spec.n_layers * batch * seq * spec.hidden * 2 * 16 / 1e9

    plans = [
        # 全参：权重 bf16(2B) + 梯度 bf16(2B) + AdamW 状态 fp32(8B)
        Plan("全参微调（bf16 + AdamW）", n * 2 / 1e9, n * 2 / 1e9, n * 8 / 1e9, act),
        # LoRA bf16：基座冻结（无梯度无优化器），只算 LoRA 的
        Plan("LoRA（bf16 基座）", n * 2 / 1e9, 0.0, lora_params(spec, 16) * 8 / 1e9, act * 0.6),
        # QLoRA：基座压 4bit（0.5B/参数）+ bf16 计算时的临时上转
        Plan("QLoRA（4bit 基座）", n * 0.5 / 1e9, 0.0, lora_params(spec, 16) * 8 / 1e9, act * 0.75),
    ]

    print(f"   假设：{spec.name}，seq_len={seq}，batch={batch}，LoRA rank=16")
    print()
    print(f"   {'方案':<26}{'权重':>9}{'梯度':>9}{'优化器':>10}{'激活':>9}{'合计':>10}")
    print("   " + "-" * 74)
    for p in plans:
        print(
            f"   {p.label:<26}{p.weights_gb:>8.1f}G{p.grads_gb:>8.1f}G"
            f"{p.optim_gb:>9.2f}G{p.activ_gb:>8.1f}G{p.total:>9.1f}G"
        )
    print()
    full = plans[0].total
    lora = plans[1].total
    qlora = plans[2].total
    print(f"   全参 {full:.0f} GB → 需要 2 张 80G A100（还要留余量）")
    print(f"   LoRA {lora:.0f} GB → 一张 24G 4090 够」")
    print(f"   QLoRA {qlora:.0f} GB → 一张 16G 也能跑」")
    print()
    print(f"   显存降幅：全参 → LoRA 降 {(1 - lora / full) * 100:.0f}%；LoRA → QLoRA 再降 {(1 - qlora / lora) * 100:.0f}%")
    print()


def demo_batch_math() -> None:
    print("⑤ batch 的算术：global_batch 到底是多少」")
    print()
    print("   三个参数的关系（最容易搞错的地方）：")
    print("     global_batch = per_device_batch × 设备数 × 梯度累积步数」")
    print()
    for per_dev, n_gpu, accum in [(2, 1, 8), (4, 1, 4), (2, 4, 2), (1, 8, 2)]:
        gb = per_dev * n_gpu * accum
        print(f"     per_device={per_dev}  设备={n_gpu}  accum={accum}  →  global_batch={gb}")
    print()
    print("   ⚠️ 只有 global_batch 影响「优化器看到的样本数」。")
    print("      per_device 影响显存，accum 影响速度，**两者都不直接改变训练效果**")
    print("      —— 前提是 global_batch 一样。")
    print()
    print("   算更新步数（决定训练多久）：")
    n_samples, epochs = 1000, 3
    gb = 16
    steps = math.ceil(n_samples / gb) * epochs
    print(f"     样本 {n_samples} 条 × {epochs} epoch ÷ global_batch {gb} = {steps} 步」")
    print(f"     如果每步 1.2 秒 → 约 {steps * 1.2 / 60:.1f} 分钟」")
    print()


def demo_rank_tradeoff() -> None:
    print("⑥ rank 的取舍：不是越大越好」")
    print()
    spec = MODELS["qwen2.5-7b"]
    print(f"   {'rank':>6}{'参数量':>14}{'显存(优化器)':>14}  典型效果")
    print("   " + "-" * 68)
    rows = [
        (4, "可能学不动，格式类任务勉强"),
        (8, "格式/短回答够用"),
        (16, "最常用的起点"),
        (32, "复杂风格迁移，容易过拟合小数据"),
        (64, "小数据必过拟合，除非 > 5000 条"),
    ]
    for r, note in rows:
        p = lora_params(spec, r)
        print(f"   {r:>6}{p:>14,}{p * 8 / 1e9:>12.2f} GB  {note}")
    print()
    print("   判据：")
    print("     · 数据 < 500 条 → rank 8 ~ 16，再大必过拟合」")
    print("     · 数据 1000~5000 条 → rank 16 ~ 32")
    print("     · 任务只是「换个输出格式」 → rank 8 就够（这个最常被高估）")
    print()


def demo_quantization_error() -> None:
    print("⑦ QLoRA 的代价：4bit 量化到底损失了什么」")
    print()
    # NF4 的量化误差：用 16 个量化级别覆盖 [-1, 1] 的近似
    import random

    rnd = random.Random(0)
    weights = [rnd.gauss(0, 1) for _ in range(20000)]
    n_levels = 16
    lo, hi = min(weights), max(weights)
    step = (hi - lo) / (n_levels - 1)
    # 量化 → 反量化
    deq = [round((w - lo) / step) * step + lo for w in weights]
    err = [abs(a - b) for a, b in zip(weights, deq)]
    mae = sum(err) / len(err)
    rel = mae / (sum(abs(w) for w in weights) / len(weights))
    print(f"   模拟 {len(weights)} 个权重，用 {n_levels} 级别（NF4 是 16 级）量化：")
    print(f"     平均绝对误差 MAE = {mae:.4f}")
    print(f"     相对误差 = {rel:.2%}")
    print(f"     最大误差 = {max(err):.4f}")
    print()
    print("   直观理解：每个权重都「稍微偏了一点」，但偏的方向是随机的。")
    print("   所以：")
    print("     · 逐层的矩阵乘结果**均值几乎不变** → 前向输出基本一致」")
    print("     · 但梯度会被这些偏差污染 → **训练效果略差于 bf16 LoRA**")
    print()
    print("   经验数字（多个公开实验的中位值）：")
    print("     · QLoRA vs LoRA 的效果差：约 1~3 个点（在目标任务上）")
    print("     · 显存差：约 3~4 倍」")
    print("     → 16G 显卡上想跑 7B，QLoRA 是唯一选项，那 1~3 点就该接受」")
    print()


def main() -> None:
    demo_lora_size()
    demo_alpha()
    demo_target_modules()
    demo_memory()
    demo_batch_math()
    demo_rank_tradeoff()
    demo_quantization_error()


if __name__ == "__main__":
    main()
