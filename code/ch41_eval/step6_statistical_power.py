"""第 42 章 step6：评测集的统计功效 —— 你的集子「测得出来」吗。

运行：
    python code/ch41_eval/step6_statistical_power.py

42.5 说「门禁阈值是业务选择」。但有个更前置的问题常被忽略：

    我的评测集**根本测不出**我想测的差异。

这一级量化三件事：
    ① 同一个观测率，样本量不同 -> 结论有多不可信（Wilson 区间）
    ② 「全绿」有多少是运气（3/n 定律：0 失败 != 0 缺陷率）
    ③ 我的集子能检出多大的差异（功效分析）

所有数字都是脚本真实算出来的。
"""
from __future__ import annotations

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - m), min(1.0, c + m)


# ================================================================ ① 小类别
def demo_interval() -> None:
    print(DPRINT)
    print("① 同一个观测率，样本量不同 -> 结论可信度差多少")
    print(DPRINT)

    print(f"  {'观测':<12} {'样本数':<8} {'Wilson 下限':<14} {'Wilson 上限':<14} {'区间宽度':<10}")
    print(f"  {'-' * 12} {'-' * 8} {'-' * 14} {'-' * 14} {'-' * 10}")

    rows = [(9, 10), (90, 100), (45, 50), (450, 500), (10, 10), (100, 100)]
    for k, n in rows:
        lo, hi = wilson(k, n)
        print(f"  {k}/{n:<10} {n:<8} {lo:<14.3f} {hi:<14.3f} {hi - lo:<10.3f}")

    lo1, hi1 = wilson(9, 10)
    lo2, hi2 = wilson(90, 100)
    print()
    print("  ---- 9/10 和 90/100 都是「90%」，但：")
    print(f"       9/10   区间 [{lo1:.3f}, {hi1:.3f}]，宽 {hi1 - lo1:.3f}")
    print(f"       90/100 区间 [{lo2:.3f}, {hi2:.3f}]，宽 {hi2 - lo2:.3f}")
    print(f"       前者宽 {(hi1 - lo1) / (hi2 - lo2):.1f} 倍。")
    print()
    print("  这对「分类最低率」门禁意味着什么：")
    print("   · 门禁写「每类 >= 85%」")
    print("   · 「发票冲红」只有 10 条，8 条通过（80%）")
    lo, hi = wilson(8, 10)
    print(f"   · 看着不达标，但区间是 [{lo:.3f}, {hi:.3f}]")
    print("   · 真实水平完全可能在 85% 以上 —— 你只是**样本不够**")
    print()
    print("  经验值：")
    print("   · 每类 >= 30 条，勉强能判「是否低于 85%」")
    print("   · 每类 >= 100 条，才能判「是否低于 92%」")
    print("   · 样本不够时，门禁应写「这一类不参与门禁，只做监控」")


# ================================================================ ② 全绿的运气
def demo_zero_failure() -> None:
    print()
    print(DPRINT)
    print("② 「全绿」有多少是运气：0 失败 != 0 缺陷率")
    print(DPRINT)

    print("  三分之一定律（rule of three）：")
    print("  n 条全过时，真实缺陷率的 95% 置信上限约为 **3/n**。")
    print()
    print(f"  {'样本数':<10} {'观测':<14} {'缺陷率 95% 上限':<18} 能说什么")
    print(f"  {'-' * 10} {'-' * 14} {'-' * 18} {'-' * 34}")

    for n in (10, 20, 30, 50, 100, 300, 1000):
        upper = 3 / n
        if upper > 0.3:
            said = "基本什么都没证明"
        elif upper > 0.1:
            said = f"缺陷率可能高达 {upper:.0%}"
        elif upper > 0.03:
            said = f"缺陷率 < {upper:.0%}"
        else:
            said = f"缺陷率 < {upper:.1%}，可以说「很稳」"
        print(f"  {n:<10} {f'{n}/{n} 全过':<14} {upper:<18.3f} {said}")

    print()
    print("  三件事必须记住：")
    print("   1. **20 条全过只能保证缺陷率 < 15%**，不能说明「没问题」。")
    print("   2. 想要「缺陷率 < 1%」，至少要 300 条全过。")
    print("   3. 所以「我们测了 20 条全过，可以上线了」这句话，")
    print("      等价于「我不知道缺陷率是多少，但大概不超过 15%」。")
    lo, _ = wilson(20, 20)
    print()
    print(f"  用 Wilson 交叉验证 20/20 全过：区间 [{lo:.3f}, 1.000]")
    print(f"  ---- 下限 {lo:.3f} 的意思是：**真实通过率可能低到 {lo:.0%}**。")


# ================================================================ ③ 功效
def demo_power() -> None:
    print()
    print(DPRINT)
    print("③ 我的评测集能检出多大的差异（功效分析）")
    print(DPRINT)

    print("  问题：A 真实 90%，B 真实 p2。用 n 条评测集，")
    print("        有多大概率得出「B 显著更好」？（双侧 α=0.05）")
    print()

    def power(n: int, p1: float, p2: float, alpha: float = 0.05) -> float:
        if n == 0:
            return 0.0
        za = 1.959963985 if alpha == 0.05 else 1.96
        se0 = math.sqrt(2 * p1 * (1 - p1) / n)
        se1 = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n)
        if se1 == 0:
            return 0.0
        z = (abs(p2 - p1) - za * se0) / se1
        return 0.5 * math.erfc(-z / math.sqrt(2))

    print(f"  {'评测集条数':<12} {'90% vs 92%':<14} {'90% vs 95%':<14} "
          f"{'90% vs 98%':<14} {'90% vs 80%(退化)':<18}")
    print(f"  {'-' * 12} {'-' * 14} {'-' * 14} {'-' * 14} {'-' * 18}")
    for n in (50, 100, 200, 500, 1000, 2000):
        print(f"  {n:<12} {power(n, 0.90, 0.92):<14.0%} {power(n, 0.90, 0.95):<14.0%} "
              f"{power(n, 0.90, 0.98):<14.0%} {power(n, 0.90, 0.80):<18.0%}")

    print()
    print("  ---- 读法（这些数字比想象的悲观）：")
    print(f"     · 100 条检出 2 个点差异的概率只有 {power(100, 0.90, 0.92):.0%}，")
    print("       基本等于抛硬币 —— 这时候「涨了 2 个点」不能当结论。")
    print(f"     · 200 条检出 5 个点：{power(200, 0.90, 0.95):.0%}")
    print(f"     · 500 条检出 5 个点：{power(500, 0.90, 0.95):.0%}（这是标准的 80% 功效点）")
    print(f"     · 100 条检出 10 个点（90% -> 80% 退化）：{power(100, 0.90, 0.80):.0%}")
    print(f"     · 200 条检出 10 个点：{power(200, 0.90, 0.80):.0%}")
    print()
    print("  **这解释了为什么「门禁只防大退化」是合理设计：**")
    print("   · 检出 10 个点退化：100 条约 63%，200 条约 88% —— 够用")
    print("   · 检出 5 个点改进：要 500 条才有 80% 把握")
    print("   · 检出 2 个点改进：2000 条也只有 56% —— 基本别想")
    print()
    print("  三个实用结论：")
    print("   1. **门禁用来防退化（掉 10 个点），不用来证明改进。**")
    print("      改进靠「单条用例从失败变通过」来确认，不靠总体率。")
    print("   2. 想验证小改进，先加样本量，别拿噪声当进步。")
    print("   3. 样本量不够时，正确的话术是「**看不出差异**」，")
    print("      不是「**没有差异**」—— 这是两件事。")


if __name__ == "__main__":
    demo_interval()
    demo_zero_failure()
    demo_power()
    print()
    print(DPRINT)
    print("step6 完成。三句话带走：")
    print("  1. 每类少于 30 条时该类结论不可信 —— 门禁应写「仅监控不拦截」。")
    print("  2. 20 条全过只能保证缺陷率 < 15%（3/n 定律）；要 < 1% 需 300 条全过。")
    print("  3. 100 条检出 10 个点退化的概率约 63%，1000 条才接近必检出；")
    print("     检出 2 个点要 2000 条以上。「看不出差异」不等于「没有差异」。")
    print(DPRINT)
