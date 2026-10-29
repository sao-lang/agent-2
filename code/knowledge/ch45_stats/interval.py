"""小样本的比率不可信：区间、要多少样本、两个版本怎么比。

不联网。三件事：
  1 同一个 95% 通过率，样本量不同，区间宽度差很多
  2 要判一个 3 个点的差异，需要多少条
  3 两个版本的差异多大才算数（区间跨不跨 0）

二项比率的区间用 Wilson，它比"p ± 1.96√(p(1-p)/n)"在小样本上更稳。
"""

from __future__ import annotations

import math

Z = 1.96


def wilson(k: int, n: int) -> tuple[float, float]:
    """Wilson 区间：小样本与极端比例都适用。"""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def required_n(p: float, half_width: float) -> int:
    """想让区间半宽小于 half_width，至少需要多少条（正态近似）。"""
    return math.ceil(Z * Z * p * (1 - p) / (half_width ** 2))


def diff_interval(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """两版通过率之差与它的 95% 区间（正态近似）。"""
    p1, p2 = k1 / n1, k2 / n2
    d = p2 - p1
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return d, d - Z * se, d + Z * se


def main() -> None:
    print("=== 1. 同一个 95%，区间差多少 ===")
    for n in (20, 100, 1000):
        k = round(0.95 * n)
        lo, hi = wilson(k, n)
        print(f"  {k}/{n} = {k / n:.0%}  区间 [{lo:.1%}, {hi:.1%}]  宽 {(hi - lo) * 100:.1f} 个点")

    print()
    print("=== 2. 要判多大的差异，需要多少条 ===")
    for hw in (0.10, 0.05, 0.03, 0.01):
        n = required_n(0.9, hw)
        print(f"  半宽 ±{hw * 100:.0f} 个点 -> 约 {n} 条")
    print("  <- 判断 3 个点的差异，量级是几百条；判断 1 个点，是上千条")

    print()
    print("=== 3. 两个版本比较：差异与区间 ===")
    cases = [
        ("基线 172/200 vs 候选 178/200", 172, 200, 178, 200),
        ("基线 172/200 vs 候选 186/200", 172, 200, 186, 200),
        ("基线 172/200 vs 候选 173/200", 172, 200, 173, 200),
        ("小样本 17/20 vs 18/20", 17, 20, 18, 20),
    ]
    for label, k1, n1, k2, n2 in cases:
        d, lo, hi = diff_interval(k1, n1, k2, n2)
        verdict = "显著" if (lo > 0 or hi < 0) else "不显著"
        print(f"  {label}")
        print(f"    差异 {d * 100:+.1f} 个点，区间 [{lo * 100:+.1f}, {hi * 100:+.1f}] -> {verdict}")

    print()
    print("=== 4. 同一条用例重复跑：稳定性本身也是比率 ===")
    runs = [1, 1, 0, 1, 1, 1, 0, 1, 1, 1]      # 10 次里过 8 次
    k, n = sum(runs), len(runs)
    lo, hi = wilson(k, n)
    print(f"  同一条任务跑 {n} 次，过 {k} 次（{k / n:.0%}）")
    print(f"  稳定性区间 [{lo:.0%}, {hi:.0%}]：区间宽说明 10 次还不够")


if __name__ == "__main__":
    main()
