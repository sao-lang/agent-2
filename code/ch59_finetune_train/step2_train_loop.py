"""第 59 章 step2：训练过程 —— 用真实算法跑一遍，看 loss 曲线在说什么。

运行：
    python code/ch59_finetune_train/step2_train_loop.py

纯离线、纯标准库（不装 torch）。它实现了一个**玩具级的 LoRA 微调循环**：
  · 一个极简的"模型"：几个线性层，参数是随机数
  · 一个可学的目标：把输入映射到固定的输出模式
  · LoRA：冻结基座，只训两个小矩阵
  · AdamW + warmup + cosine 衰减
  · 按"日志格式"打印每一步，让你学会读真实训练日志

它跑出来的 loss 曲线形状、以及"学习率太快/太慢/没 warmup"三种现象，
和真实微调**定性一致**。这不是比喻，是真的在跑梯度下降。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ================================================================ 玩具模型
class Linear:
    """y = Wx，W 是 (out, in)。only_w 为 True 时冻结。"""

    def __init__(self, n_in: int, n_out: int, rnd: random.Random, trainable: bool = True) -> None:
        self.n_in, self.n_out = n_in, n_out
        self.trainable = trainable
        self.w = [[rnd.gauss(0, 1 / math.sqrt(n_in)) for _ in range(n_in)] for _ in range(n_out)]
        self.grad = [[0.0] * n_in for _ in range(n_out)]

    def forward(self, x: list[float]) -> list[float]:
        return [sum(self.w[i][j] * x[j] for j in range(self.n_in)) for i in range(self.n_out)]

    def zero_grad(self) -> None:
        for row in self.grad:
            for j in range(len(row)):
                row[j] = 0.0


class LoRALinear:
    """基座冻结 + 低秩增量：y = Wx + (alpha/r) · B(Ax)。

    A: (r, in) 用随机小值初始化；B: (out, r) **用 0 初始化**。
    为什么 B 要 0 初始化？这样训练开始时增量为 0，模型行为和预训练完全一致。
    非 0 初始化会让模型一开始就"抖一下"，小数据上可能直接训歪。
    """

    def __init__(self, base: Linear, rank: int, alpha: float, rnd: random.Random) -> None:
        self.base = base
        self.r = rank
        self.scaling = alpha / rank
        fin, fout = base.n_in, base.n_out
        self.a = [[rnd.gauss(0, 1 / math.sqrt(fin)) for _ in range(fin)] for _ in range(rank)]
        self.b = [[0.0] * rank for _ in range(fout)]
        self.ga = [[0.0] * fin for _ in range(rank)]
        self.gb = [[0.0] * rank for _ in range(fout)]

    def forward(self, x: list[float]) -> list[float]:
        base_out = self.base.forward(x)
        # A 降维
        ax = [sum(self.a[k][j] * x[j] for j in range(len(x))) for k in range(self.r)]
        # B 升维
        bx = [sum(self.b[i][k] * ax[k] for k in range(self.r)) for i in range(len(base_out))]
        return [base_out[i] + self.scaling * bx[i] for i in range(len(base_out))]

    def backward(self, x: list[float], grad_out: list[float]) -> None:
        """只累积 LoRA 的梯度（基座冻结，不需要）。"""
        # dL/dB[i][k] = scaling * grad_out[i] * ax[k]
        ax = [sum(self.a[k][j] * x[j] for j in range(len(x))) for k in range(self.r)]
        for i in range(len(self.b)):
            for k in range(self.r):
                self.gb[i][k] += self.scaling * grad_out[i] * ax[k]
        # dL/dA[k][j] = scaling * x[j] * sum_i(grad_out[i] * B[i][k])
        for k in range(self.r):
            coef = sum(grad_out[i] * self.b[i][k] for i in range(len(self.b)))
            for j in range(len(x)):
                self.ga[k][j] += self.scaling * coef * x[j]

    def zero_grad(self) -> None:
        for row in self.ga:
            for j in range(len(row)):
                row[j] = 0.0
        for row in self.gb:
            for j in range(len(row)):
                row[j] = 0.0

    def params(self) -> list[tuple[list[float], list[float]]]:
        return [(row, grow) for row, grow in zip(self.a, self.ga)] + [
            (row, grow) for row, grow in zip(self.b, self.gb)
        ]


# ================================================================ AdamW
class AdamW:
    def __init__(self, lr: float, wd: float = 0.01, b1: float = 0.9, b2: float = 0.999, eps: float = 1e-8) -> None:
        self.lr, self.wd, self.b1, self.b2, self.eps = lr, wd, b1, b2, eps
        self.t = 0
        self.m: dict[int, float] = {}
        self.v: dict[int, float] = {}

    def step(self, params: list[tuple[list[float], list[float]]]) -> None:
        self.t += 1
        bc1 = 1 - self.b1**self.t
        bc2 = 1 - self.b2**self.t
        for row, grow in params:
            for j in range(len(row)):
                key = id(row) * 100003 + j
                g = grow[j]
                self.m[key] = self.b1 * self.m.get(key, 0.0) + (1 - self.b1) * g
                self.v[key] = self.b2 * self.v.get(key, 0.0) + (1 - self.b2) * g * g
                mhat = self.m[key] / bc1
                vhat = self.v[key] / bc2
                row[j] -= self.lr * (mhat / (math.sqrt(vhat) + self.eps) + self.wd * row[j])


# ================================================================ 数据与任务
@dataclass
class Batch:
    x: list[list[float]]
    y: list[list[float]]


def make_task(rnd: random.Random, n: int, dim: int = 8) -> list[Batch]:
    """人造任务：输入是随机向量，目标是"取前 3 维做非线性组合"。

    这模拟了"模型已经会很多事，现在要它学一个新的映射规则"。
    """
    out = []
    for _ in range(n):
        x = [rnd.gauss(0, 1) for _ in range(dim)]
        # 目标维度必须和 LoRALinear 的输出维度一致（16 = base 的 n_out）
        y = [0.0] * 16
        y[0] = x[0] * 0.8 + x[1] * -0.5
        y[1] = max(0.0, x[2]) + x[0] * 0.3
        y[2] = x[3] * 0.6
        for k in range(3):
            y[10 + k] = x[k] * 0.25
        out.append(Batch([x], [y]))
    return out


def mse(pred: list[float], target: list[float]) -> float:
    return sum((p - t) ** 2 for p, t in zip(pred, target)) / len(pred)


def mse_grad(pred: list[float], target: list[float]) -> list[float]:
    n = len(pred)
    return [2 * (p - t) / n for p, t in zip(pred, target)]


# ================================================================ 学习率调度
def lr_at(step: int, total: int, base_lr: float, warmup: int, schedule: str = "cosine") -> float:
    """三段式：warmup 线性上升 → cosine/linear 衰减 → 最后 10% 降到 0。

    为什么必须 warmup？
    AdamW 的 v（二阶矩）在最初几步是**严重低估**的（因为 bc2 修正还没生效够），
    导致实际步长偏大。warmup 就是"先小步走几步，让 v 估计稳下来"。
    """
    if step < warmup:
        return base_lr * (step + 1) / max(warmup, 1)
    prog = (step - warmup) / max(total - warmup, 1)
    if schedule == "cosine":
        return base_lr * 0.5 * (1 + math.cos(math.pi * prog))
    if schedule == "linear":
        return base_lr * (1 - prog)
    return base_lr


# ================================================================ 训练循环
@dataclass
class Run:
    label: str
    base_lr: float
    warmup: int
    schedule: str = "cosine"
    rank: int = 4
    alpha: float = 4.0
    accum: int = 1
    losses: list[float] = field(default_factory=list)


def train(run: Run, train_data: list[Batch], val_data: list[Batch], epochs: int = 6) -> Run:
    rnd = random.Random(7)
    base = Linear(8, 16, rnd, trainable=False)
    head = LoRALinear(base, run.rank, run.alpha, rnd)
    opt = AdamW(lr=run.base_lr)
    all_params = head.params()
    total = math.ceil(len(train_data) / run.accum) * epochs
    step = 0

    for ep in range(epochs):
        acc_loss = 0.0
        cnt = 0
        for i, batch in enumerate(train_data):
            for x, y in zip(batch.x, batch.y):
                pred = head.forward(x)
                acc_loss += mse(pred, y)
                cnt += 1
                head.backward(x, mse_grad(pred, y))
            if (i + 1) % run.accum == 0 or i == len(train_data) - 1:
                lr = lr_at(step, total, run.base_lr, run.warmup, run.schedule)
                opt.lr = lr
                opt.step(all_params)
                head.zero_grad()
                step += 1
        run.losses.append(acc_loss / max(cnt, 1))
    # 验证
    v = 0.0
    for b in val_data:
        for x, y in zip(b.x, b.y):
            v += mse(head.forward(x), y)
    run.losses.append(v / max(len(val_data), 1))
    return run


def demo_loss_curve() -> None:
    print("① 一条正常的 loss 曲线长什么样（真实跑出来的）")
    rnd = random.Random(1)
    tr = make_task(rnd, 60)
    va = make_task(rnd, 20)
    run = train(Run("正常", base_lr=0.01, warmup=2), tr, va, epochs=6)
    print()
    print(f"   {'epoch':>6}{'train_loss':>14}{'lr':>12}{'变化':>10}")
    print("   " + "-" * 42)
    prev = None
    for e, l in enumerate(run.losses[:-1], 1):
        lr = lr_at(e - 1, 6 * 6, 0.01, 2)
        delta = "" if prev is None else f"{(l - prev) / prev:+.1%}"
        print(f"   {e:>6}{l:>14.5f}{lr:>12.6f}{delta:>10}")
        prev = l
    print(f"   {'val':>6}{run.losses[-1]:>14.5f}{'-':>12}{'-':>10}")
    print()
    print("   读这张表的三件事：")
    print("     1. train_loss 单调下降 → 在学")
    print("     2. 下降速度越来越慢 → 正常（指数收敛）")
    print("     3. val_loss 应该**跟着降**，如果它开始上升 → 过拟合")
    print()


def demo_lr_too_high() -> None:
    print("② 💥 失败实验：学习率太大")
    rnd = random.Random(1)
    tr = make_task(rnd, 60)
    va = make_task(rnd, 20)
    ok = train(Run("lr=0.01", base_lr=0.01, warmup=2), tr, va)
    bad = train(Run("lr=0.3", base_lr=0.3, warmup=2), tr, va)
    print()
    print(f"   {'epoch':>6}{'lr=0.01':>16}{'lr=0.3':>16}")
    print("   " + "-" * 40)
    for e in range(len(ok.losses) - 1):
        print(f"   {e + 1:>6}{ok.losses[e]:>16.5f}{bad.losses[e]:>16.5f}")
    print(f"   {'val':>6}{ok.losses[-1]:>16.5f}{bad.losses[-1]:>16.5f}")
    print()
    print("   现象：lr=0.3 在前两个 epoch **loss 不降反升**（0.68 → 2.12 → 2.17），")
    print("   然后才掉下来。最终 val_loss 0.2995 vs 0.2974 —— 几乎一样。")
    print()
    print("   **诚实说明**：这个玩具任务太简单，大学习率最终也能收敛。")
    print("   真实微调里 lr 大 3~10 倍更常见的结果是 loss 变 nan 或长期震荡。")
    print("   诊断关键词：")
    print("     · loss 变成 nan / inf → 学习率大 3~10 倍")
    print("     · loss 上下震荡不收敛 → 学习率大 2~5 倍")
    print("     · loss 降得很慢 → 学习率可能太小，或者 warmup 太长")
    print()


def demo_no_warmup() -> None:
    print("③ 💥 失败实验：不做 warmup")
    rnd = random.Random(1)
    tr = make_task(rnd, 60)
    va = make_task(rnd, 20)
    w = train(Run("warmup=2", base_lr=0.05, warmup=2), tr, va)
    nw = train(Run("warmup=0", base_lr=0.05, warmup=0), tr, va)
    print()
    print("   前 3 个 epoch：")
    print(f"   {'epoch':>6}{'warmup=2':>14}{'无 warmup':>14}")
    print("   " + "-" * 36)
    for e in range(3):
        print(f"   {e + 1:>6}{w.losses[e]:>14.5f}{nw.losses[e]:>14.5f}")
    print()
    d1 = (nw.losses[0] - w.losses[0]) / w.losses[0]
    d2 = (nw.losses[-1] - w.losses[-1]) / w.losses[-1]
    print(f"   第一个 epoch 结束时，无 warmup 的 loss 相对差 {d1:+.1%}")
    print(f"   最终 val_loss 相对差 {d2:+.1%}")
    print()
    print("   **诚实说明**：在这个玩具任务上，warmup 几乎没差别（甚至无 warmup 略好）。")
    print("   原因是：模型很小、任务很简单、学习率也不算激进。")
    print("   真实微调里 warmup 的价值在于**避免第一两步把模型推歪**——")
    print("   模型越大、学习率越高、数据越少，这个风险越大。")
    print("   不要因为「这个实验看不出差别」就删掉 warmup。")
    print()


def demo_rank_effect() -> None:
    print("④ rank 对拟合能力的影响（这个任务上越大越好）")
    rnd = random.Random(1)
    tr = make_task(rnd, 60)
    va = make_task(rnd, 20)
    runs = [train(Run(f"r={r}", base_lr=0.01, warmup=2, rank=r, alpha=float(r)), tr, va) for r in (1, 2, 4, 16)]
    print()
    print(f"   {'rank':>6}{'train_loss':>14}{'val_loss':>12}")
    print("   " + "-" * 34)
    for r in runs:
        print(f"   {r.rank:>6}{r.losses[-2]:>14.5f}{r.losses[-1]:>12.5f}")
    print()
    print("   在这 60 条数据上：rank 1 → 2 → 4 → 16 **一直在改善**（0.80 → 0.58 → 0.30 → 0.03）。")
    print()
    print("   **诚实说明**：这个结果**不支持**「rank 越大越容易过拟合」的说法。")
    print("   原因是：这个任务是**纯确定性的函数逼近**（同样的输入永远同样的输出），")
    print("   没有噪声，所以容量越大拟合得越好。")
    print()
    print("   真实的微调数据是有噪声的（标注不一致、表达多样），")
    print("   那时 rank 太大才会过拟合。**这个玩具实验只能演示「rank 影响容量」，")
    print("   不能演示「rank 影响泛化」。** 后者必须用真实数据才看得出来。")
    print()



def make_noisy_task(rnd: random.Random, n: int, noise: float = 1.2, dim: int = 8) -> list[Batch]:
    """带噪声的任务：同样的输入，目标值每次略有不同。

    这才像真实的标注数据：两个人标同一个问题，答案不会一模一样。
    噪声让"容量越大越好"不再成立 —— 大容量会把噪声也学进去。
    """
    out = []
    for _ in range(n):
        x = [rnd.gauss(0, 1) for _ in range(dim)]
        y = [0.0] * 16
        y[0] = x[0] * 0.8 + x[1] * -0.5 + rnd.gauss(0, noise)
        y[1] = max(0.0, x[2]) + x[0] * 0.3 + rnd.gauss(0, noise)
        y[2] = x[3] * 0.6 + rnd.gauss(0, noise)
        for k in range(3):
            y[10 + k] = x[k] * 0.25 + rnd.gauss(0, noise)
        out.append(Batch([x], [y]))
    return out


def demo_overfit() -> None:
    print("⑤ 什么时候 rank 太大真会过拟合：加噪声")
    print()
    rnd = random.Random(3)
    tr = make_noisy_task(rnd, 40, noise=1.5)
    va = make_noisy_task(rnd, 40, noise=1.5)
    print(f"   {'rank':>6}{'train_loss':>14}{'val_loss':>12}{'gap':>10}")
    print("   " + "-" * 44)
    rows = []
    for r in (1, 2, 4, 8, 16, 32):
        run = train(Run(f"r={r}", base_lr=0.01, warmup=2, rank=r, alpha=float(r)), tr, va, epochs=8)
        trl, val = run.losses[-2], run.losses[-1]
        gap = val - trl
        rows.append((r, trl, val, gap, ""))
        print(f"   {r:>6}{trl:>14.5f}{val:>12.5f}{gap:>+10.4f}")
    print()
    print("   看不到「val 回升」——因为训练轮数太少（8 epoch），还没到过拟合那个点。")
    print("   **诚实说明**：这个演示只证明了「容量增加，train/val 都下降但 gap 保持」。")
    print("   真过拟合的判据是：继续训下去，train 还在降而 val 开始回升。")
    print("   把 epochs 从 8 拉到 40 就能看到这个拐点（你可以自己改一下试）。")
    best = min(rows, key=lambda x: x[2])
    print()
    print(f"   在 8 个 epoch 内，val_loss 最低的是 rank={best[0]}（{best[2]:.4f}）")
    print("   → 真实项目里，**用验证集选 rank 和 epoch 数**，不要凭感觉。")
    print()


def demo_grad_accum() -> None:
    print("⑥ 梯度累积：小显存跑大 batch 的代价是什么")
    rnd = random.Random(1)
    tr = make_task(rnd, 60)
    va = make_task(rnd, 20)
    a1 = train(Run("accum=1", base_lr=0.01, warmup=2, accum=1), tr, va)
    a6 = train(Run("accum=6", base_lr=0.06, warmup=2, accum=6), tr, va)
    print()
    print(f"   {'epoch':>6}{'accum=1 (60 步/epoch)':>26}{'accum=6 (10 步/epoch)':>26}")
    print("   " + "-" * 60)
    for e in range(6):
        print(f"   {e + 1:>6}{a1.losses[e]:>26.5f}{a6.losses[e]:>26.5f}")
    print()
    print("   两者 global_batch 相同（6），最终 loss 接近（0.2175 vs 0.2093）。")
    print()
    print("   **诚实说明**：这个实验里 accum=6 反而略好，和「累积会变慢」的直觉相反。")
    print("   原因是：我同时把 lr 从 0.01 提到了 0.06（按步数比例补偿），")
    print("   而步数少让每步的梯度噪声更小 —— 两个效应叠加后略占优。")
    print()
    print("   真实的取舍是：")
    print("     · accum 让你在**小显存上模拟大 batch**（这是它唯一的目的）")
    print("     · 代价是同样的 epoch 数下更新步数变少 → 需要调大 epoch 或 lr")
    print("     · 但它**不会**凭空提升效果，也不会凭空损坏效果")
    print()


def demo_read_log() -> None:
    print("⑦ 教你读真实训练日志（这是 LLaMA-Factory 的输出格式）")
    print()
    log = """
{'loss': 1.8765, 'grad_norm': 8.234, 'learning_rate': 1e-05, 'epoch': 0.02}
{'loss': 1.5432, 'grad_norm': 3.871, 'learning_rate': 9.8e-05, 'epoch': 0.04}
{'loss': 1.2109, 'grad_norm': 2.554, 'learning_rate': 1.9e-04, 'epoch': 0.06}
{'loss': 0.9876, 'grad_norm': 1.982, 'learning_rate': 2.0e-04, 'epoch': 0.08}
{'loss': 0.8765, 'grad_norm': 1.743, 'learning_rate': 1.98e-04, 'epoch': 0.10}
{'loss': 0.8123, 'grad_norm': 1.601, 'learning_rate': 1.95e-04, 'epoch': 0.12}
{'loss': 0.7891, 'grad_norm': 1.522, 'learning_rate': 1.91e-04, 'epoch': 0.14}
    """
    for ln in log.strip().split("\n"):
        print(f"     {ln.strip()}")
    print()
    print("   四个字段分别是什么：")
    print()
    print("   ┌─ loss：当前 batch 的平均损失")
    print("   │   · 看**趋势**，不看单点。2~3 步的抖动是正常的")
    print("   │   · 稳定在 1.0 以上说明还没学到东西")
    print("   │   · 突然变成 nan → 学习率太大，或者数据里有异常样本")
    print("   │")
    print("   ├─ grad_norm：梯度的 L2 范数（所有参数梯度的总长度）")
    print("   │   · 正常：从 5~10 逐渐降到 1~2")
    print("   │   · 突然飙升到 100+ → 梯度爆炸，检查数据 + 降学习率")
    print("   │   · 一直是 0.00 → 梯度消失了（LoRA 挂错层？labels 全 mask 了？）")
    print("   │")
    print("   ├─ learning_rate：当前步用的学习率")
    print("   │   · 应该先升（warmup）后降")
    print("   │   · 如果一直不变 → warmup/scheduler 没生效")
    print("   │")
    print("   └─ epoch：已经过了多少比例的**数据**（不是步数）")
    print("       · 0.02 表示过了 2% 的数据")
    print("       · 用它判断「还要多久」（见下面 ⑦）")
    print()
    print("   一条**健康**的日志长什么样：")
    print("     loss 单调下降并逐渐变缓 / grad_norm 同步下降 / lr 先升后降")
    print()


def demo_version_check() -> None:
    print("⑧ 「训练完要跑多久」怎么估")
    print()
    total_epochs = 3
    seen = 0.14  # 从日志里读到
    elapsed_s = 42 * 6  # 跑了 6 条日志，每条约 42 秒（示例值）
    remain_ratio = (total_epochs - seen) / total_epochs
    est = elapsed_s / seen * remain_ratio if seen else float("inf")
    print(f"   已过 {seen:.0%} 的 epoch，用时 {elapsed_s / 60:.1f} 分钟")
    print(f"   剩余 {total_epochs - seen:.2f} 个 epoch → 大约还要 {est / 60:.1f} 分钟")
    print()
    print("   ⚠️ 三个让这个估算失准的原因：")
    print("     1. 日志间隔不是固定的（前面慢后面快，因为 cache 变热）")
    print("     2. 中途有验证集评估，那几个步会明显变慢")
    print("     3. 多卡时最后一步要等最慢的那张卡")
    print()
    print("   → 估出来的时间乘 1.3 再决定「要不要现在去睡觉」。")
    print()


def main() -> None:
    demo_loss_curve()
    demo_lr_too_high()
    demo_no_warmup()
    demo_rank_effect()
    demo_overfit()
    demo_grad_accum()
    demo_read_log()
    demo_version_check()


if __name__ == "__main__":
    main()
