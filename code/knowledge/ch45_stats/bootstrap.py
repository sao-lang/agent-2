"""分位数与计数的区间：P95 没有解析式，事故数也不是普通比率。

不联网，只用标准库。三件事：
  1 一组 40 个延迟样本，算 P50 / P95 / P99，并用 bootstrap 给 P95 一个区间
  2 同一个 P95，正态近似与 bootstrap 的区间宽度差多少 —— 长尾上正态会低估
  3 一天 3 次事故的区间：泊松精确区间，用累积概率二分出来

bootstrap 用固定随机种子，所以输出可复现。
"""

from __future__ import annotations

import math
import random

LATENCY_MS = [
    820, 910, 940, 980, 1010, 1050, 1080, 1100, 1130, 1160,
    1180, 1210, 1240, 1260, 1290, 1310, 1340, 1360, 1390, 1420,
    1450, 1480, 1510, 1550, 1590, 1630, 1680, 1740, 1810, 1890,
    1980, 2100, 2260, 2480, 2760, 3180, 3820, 4900, 7200, 12400,
]
RUNS = 2_000


def quantile(xs: list[float], q: float) -> float:
    """线性插值分位（与 numpy 的默认口径一致）。"""
    s = sorted(xs)
    if not s:
        return 0.0
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return s[int(pos)]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def bootstrap_ci(xs: list[float], q: float, runs: int = RUNS,
                 seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    vals = []
    for _ in range(runs):
        sample = [xs[rng.randrange(len(xs))] for _ in xs]
        vals.append(quantile(sample, q))
    return quantile(vals, 0.025), quantile(vals, 0.975)


def normal_ci(xs: list[float], q: float) -> tuple[float, float]:
    """把分位数当均值做正态近似 —— 用来演示它为什么在长尾上不可靠。"""
    n = len(xs)
    p = quantile(xs, q)
    se = math.sqrt(sum((x - p) ** 2 for x in xs) / (n - 1)) / math.sqrt(n)
    return p - 1.96 * se, p + 1.96 * se


def poisson_cdf(k: int, lam: float) -> float:
    total = 0.0
    term = math.exp(-lam)
    for i in range(0, k + 1):
        if i:
            term *= lam / i
        total += term
    return total


def poisson_ci(k: int, alpha: float = 0.05) -> tuple[float, float]:
    """精确泊松区间：解 P(X>=k; lam)=alpha/2（下界）与 P(X<=k; lam)=alpha/2（上界）。"""
    def lower(lam: float) -> float:
        return 1.0 - poisson_cdf(k - 1, lam) if k > 0 else 1.0

    def upper(lam: float) -> float:
        return poisson_cdf(k, lam)

    # 下界：P(X>=k) 随 lam 增大而增大
    lo_a, lo_b = 0.0, max(k, 1) * 20.0
    for _ in range(80):
        mid = (lo_a + lo_b) / 2
        if lower(mid) > alpha / 2:
            lo_b = mid
        else:
            lo_a = mid
    # 上界：P(X<=k) 随 lam 增大而减小
    hi_a, hi_b = 0.0, max(k, 1) * 20.0
    for _ in range(80):
        mid = (hi_a + hi_b) / 2
        if upper(mid) > alpha / 2:
            hi_a = mid
        else:
            hi_b = mid
    return lo_a, hi_a


def main() -> None:
    xs = sorted(LATENCY_MS)
    n = len(xs)
    print(f"=== 1. {n} 个延迟样本 ===")
    print(f"  最小 {xs[0]}ms  中位 {quantile(xs, 0.5):.0f}ms  "
          f"最大 {xs[-1]}ms")
    for q in (0.5, 0.95, 0.99):
        lo, hi = bootstrap_ci(xs, q)
        print(f"  P{q * 100:.0f} = {quantile(xs, q):>7.0f}ms   "
              f"bootstrap 区间 [{lo:.0f}, {hi:.0f}]  宽 {hi - lo:.0f}ms")

    print()
    print("=== 2. 同一个 P95，两种区间 ===")
    p95 = quantile(xs, 0.95)
    nlo, nhi = normal_ci(xs, 0.95)
    blo, bhi = bootstrap_ci(xs, 0.95)
    print(f"  点估计 {p95:.0f}ms")
    print(f"  正态近似 [{nlo:.0f}, {nhi:.0f}]  宽 {nhi - nlo:.0f}ms")
    print(f"  bootstrap [{blo:.0f}, {bhi:.0f}]  宽 {bhi - blo:.0f}ms")
    print(f"  <- 正态区间比 bootstrap 窄 {1 - (nhi - nlo) / (bhi - blo):.0%}，"
          f"因为尾部几个样本的权重没有被它算进去")
    print("     结论：分位数报区间只能用重采样，不能用均值的公式")

    print()
    print("=== 3. 事故计数：一天 3 次 ===")
    for k in (0, 1, 3, 10):
        lo, hi = poisson_ci(k)
        ratio = "—" if lo == 0 else f"{hi / lo:.1f} 倍"
        print(f"  {k:>2} 次 -> 95% 区间 [{lo:.2f}, {hi:.2f}]   上界/下界 {ratio}")
    print("  <- 3 次的区间上界到 8.8：'这周事故变多'在一天 3 次上判不出来，要看一周合计")

    print()
    print("=== 4. 一天的样本够不够判'变慢' ===")
    print(f"  P95 的点估计 {p95:.0f}ms，区间 [{blo:.0f}, {bhi:.0f}]："
          f"区间跨度是点估计的 {bhi / p95:.1f} 倍")
    print("  如果下个月 P95 变成 4000ms，它仍落在这个区间里——这一天判不了，要多天合计")


if __name__ == "__main__":
    main()
