"""两条门禁规则：比率看绝对差，非比率看相对变化。

不联网。四个候选改动各带三项指标，逐条过门禁：

  回归判定（质量）  绝对差 <= -2 个点 -> fail；-2 到 0 之间 -> warn；其余 pass
  改善说明（质量）  绝对差 >= +2 个点且区间不跨 0，才允许说"变好了"
  非比率判定        成本涨幅 > 5% 或 P95 涨幅 > 10% -> fail

门禁只回答"能不能发"，不回答"有没有变好"——后者要单独证明。
"""

from __future__ import annotations

import math

Z = 1.96
REGRESSION_PP = 0.02          # 2 个百分点的绝对差
RULE = {"cost": 0.05, "p95": 0.10}

BASELINE = {"pass": (172, 200), "cost": 0.0120, "p95": 8.4}

CANDIDATES = [
    ("C1 提示词微调", (178, 200), 0.0120, 8.4),
    ("C2 换模型", (186, 200), 0.0134, 8.9),
    ("C3 加语义缓存", (172, 200), 0.0088, 7.9),
    ("C4 加重排", (180, 200), 0.0156, 9.6),
]


def diff_ci(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    p1, p2 = k1 / n1, k2 / n2
    d = p2 - p1
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return d, d - Z * se, d + Z * se


def regression(k1: int, n1: int, k2: int, n2: int) -> tuple[str, str]:
    d, lo, hi = diff_ci(k1, n1, k2, n2)
    if d <= -REGRESSION_PP:
        return "fail", f"绝对差 {d * 100:+.1f} 个点，超过 -2 的回归线"
    if d < 0:
        return "warn", f"绝对差 {d * 100:+.1f} 个点，小幅下降（区间 [{lo * 100:+.1f}, {hi * 100:+.1f}]）"
    return "pass", f"绝对差 {d * 100:+.1f} 个点，未触及回归线"


def improvement(k1: int, n1: int, k2: int, n2: int) -> str:
    d, lo, hi = diff_ci(k1, n1, k2, n2)
    if d >= REGRESSION_PP and lo > 0:
        return f"显著改善 {d * 100:+.1f} 个点（[{lo * 100:+.1f}, {hi * 100:+.1f}]）"
    if d >= REGRESSION_PP:
        return f"看起来变好 {d * 100:+.1f} 个点，但区间跨 0，不能算数"
    return "无提升"


def ratio_verdict(name: str, base: float, cand: float) -> tuple[str, str]:
    rel = (cand - base) / base
    limit = RULE[name]
    if rel > limit:
        return "fail", f"{name} 涨 {rel:+.1%}，超过上限 {limit:.0%}"
    if rel > limit * 0.6:
        return "warn", f"{name} 涨 {rel:+.1%}，接近上限 {limit:.0%}"
    return "pass", f"{name} {rel:+.1%}，在 {limit:.0%} 之内"


def combine(*verdicts: tuple[str, str]) -> str:
    order = {"pass": 0, "warn": 1, "fail": 2}
    return max(verdicts, key=lambda v: order[v[0]])[0]


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    k1, n1 = BASELINE["pass"]
    print(f"=== 基线：质量 {k1}/{n1} = {k1 / n1:.0%}，成本 {BASELINE['cost']:.4f} 元，"
          f"P95 {BASELINE['p95']}s ===")
    print(f"  门禁：质量绝对差回归线 -2 个点；成本上限 +{RULE['cost']:.0%}，"
          f"P95 上限 +{RULE['p95']:.0%}")

    print()
    print("=== 逐条判定 ===")
    for name, (k2, n2), cost, p95 in CANDIDATES:
        reg = regression(k1, n1, k2, n2)
        imp = improvement(k1, n1, k2, n2)
        c = ratio_verdict("cost", BASELINE["cost"], cost)
        l = ratio_verdict("p95", BASELINE["p95"], p95)
        verdict = combine(reg, c, l)
        print(f"  {pad(name, 16)}{verdict.upper()}")
        print(f"    [回归] {reg[1]}")
        print(f"    [改善] {imp}")
        print(f"    [成本] {c[1]}")
        print(f"    [延迟] {l[1]}")

    print()
    print("=== 汇总 ===")
    header = pad("候选", 16) + pad("质量", 8) + pad("成本", 10) + pad("P95", 8) + "门禁"
    print("  " + header)
    for name, (k2, n2), cost, p95 in CANDIDATES:
        reg = regression(k1, n1, k2, n2)
        c = ratio_verdict("cost", BASELINE["cost"], cost)
        l = ratio_verdict("p95", BASELINE["p95"], p95)
        verdict = combine(reg, c, l)
        print("  " + pad(name, 16) + pad(f"{k2}/{n2}", 8)
              + pad(f"{cost:.4f}", 10) + pad(f"{p95:.1f}", 8) + verdict)


if __name__ == "__main__":
    main()
