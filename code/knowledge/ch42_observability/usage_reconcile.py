"""成本口径对账，与 prompt 版本的 A/B。

不联网。两段：
  1 同一批调用，三个数对不上：厂商账单、平台 usage、自家 span 求和。差额拆成两项：
    重试、被中断的流；另有缓存计价口径这一项单独算
  2 两版 prompt 在同一批 40 条用例上的对比：只有"版本 + 标签 + 用例集"三样都固定，
    这个对比才成立

单价是示例值（每百万 token），不是任何厂商的报价；数字用来说明口径差在哪。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PRICE = {"input": 1.0, "output": 4.0, "cache": 0.1}     # 元 / 百万 token
Z = 1.96


@dataclass
class Attempt:
    step: str
    attempt: int
    status: str                 # ok / timeout / aborted
    input_tokens: int
    output_tokens: int          # 厂商计费的输出 token
    cache_tokens: int = 0
    observed_output: int = -1   # 我们实际收到的输出 token（-1 表示相同）
    recorded: bool = True       # 我们的 span 是否记了这一条

    @property
    def seen_out(self) -> int:
        return self.output_tokens if self.observed_output < 0 else self.observed_output

    @property
    def money(self) -> float:
        return (self.input_tokens * PRICE["input"]
                + self.output_tokens * PRICE["output"]
                + self.cache_tokens * PRICE["cache"]) / 1_000_000


ATTEMPTS = [
    Attempt("step-1 定位", 1, "ok", 9_800, 320),
    Attempt("step-2 读政策", 1, "timeout", 10_400, 0, recorded=False),
    Attempt("step-2 读政策", 2, "ok", 10_400, 280, 6_000),
    Attempt("sub:改写查询", 1, "ok", 3_600, 140),
    Attempt("sub:摘要", 1, "ok", 18_000, 520),
    Attempt("step-3 写文件", 1, "aborted", 7_200, 180, observed_output=120),
]


def money(inp: int, out: int, cache: int, cache_as_input: bool = False) -> float:
    if cache_as_input:
        return ((inp + cache) * PRICE["input"] + out * PRICE["output"]) / 1_000_000
    return (inp * PRICE["input"] + out * PRICE["output"]
            + cache * PRICE["cache"]) / 1_000_000


def wilson(k: int, n: int) -> tuple[float, float]:
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def diff_ci(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    p1, p2 = k1 / n1, k2 / n2
    d = p2 - p1
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return d, d - Z * se, d + Z * se


def reconcile() -> None:
    print("=== 1. 一次重试、一次中断，账单与记录怎么会差 ===")
    print(f"  {'步骤':<16}{'次':<4}{'状态':<9}{'输入':>7}{'输出':>6}{'缓存':>7}"
          f"{'金额':>10}  记录")
    for a in ATTEMPTS:
        print(f"  {a.step:<16}{a.attempt:<4}{a.status:<9}{a.input_tokens:>7}"
              f"{a.output_tokens:>6}{a.cache_tokens:>7}{a.money:>10.6f}"
              f"  {'是' if a.recorded else '否'}")

    vendor = sum(a.money for a in ATTEMPTS)
    rec = [a for a in ATTEMPTS if a.recorded]
    plat = money(sum(a.input_tokens for a in rec),
                 sum(a.seen_out for a in rec),
                 sum(a.cache_tokens for a in rec))
    plat_bad = money(sum(a.input_tokens for a in rec),
                     sum(a.seen_out for a in rec),
                     sum(a.cache_tokens for a in rec),
                     cache_as_input=True)

    retry = next(a for a in ATTEMPTS if not a.recorded)
    aborted = next(a for a in ATTEMPTS if a.status == "aborted")
    stream_gap = (aborted.output_tokens - aborted.seen_out) * PRICE["output"] / 1_000_000

    print()
    print("=== 2. 三个数 ===")
    print(f"  厂商账单       {vendor:>9.6f} 元   按每一次请求计费（含重试与被中断的流）")
    print(f"  平台 usage     {plat:>9.6f} 元   只按最终成功的那一次、且只按收到的 token")
    print(f"  自家 span 求和 {plat:>9.6f} 元   与平台同源：49000 / 1380 / 6000")
    print(f"  差额           {vendor - plat:>9.6f} 元")
    print(f"    重试的那一次   {retry.money:>9.6f} 元  {retry.step} 超时，输入仍被计费")
    print(f"    流被中断       {stream_gap:>9.6f} 元  厂商记 180 输出，我们只收到 120")
    print(f"    两项合计       {retry.money + stream_gap:>9.6f} 元")
    print()
    print(f"  如果平台把缓存按输入价算：{plat_bad:.6f} 元 vs 正确口径 {plat:.6f} 元，"
          f"差 {plat_bad - plat:.6f} 元")
    print("  <- 三个数都可以是对的：差的是'计费边界'，不是谁算错了")


def prompt_ab() -> None:
    print()
    print("=== 3. 两版 prompt 在同一批 40 条用例上 ===")
    n = 40
    v1, v2 = 33, 36
    lo1, hi1 = wilson(v1, n)
    lo2, hi2 = wilson(v2, n)
    d, lo, hi = diff_ci(v1, n, v2, n)
    print(f"  v1（prod）    {v1}/{n} = {v1 / n:.1%}  区间 [{lo1:.1%}, {hi1:.1%}]")
    print(f"  v2（staging） {v2}/{n} = {v2 / n:.1%}  区间 [{lo2:.1%}, {hi2:.1%}]")
    print(f"  差异 {d * 100:+.1f} 个点，区间 [{lo * 100:+.1f}, {hi * 100:+.1f}]"
          f" -> {'显著' if lo > 0 or hi < 0 else '不显著'}")
    print("  <- 方向是正的，但 40 条判不了 7.5 个点；要判它，先把用例加到几百条")
    print("     在此之前 v2 只能留在 staging 标签，prod 仍指 v1，回滚就是改一个标签")


def main() -> None:
    reconcile()
    prompt_ab()


if __name__ == "__main__":
    main()
