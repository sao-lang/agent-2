"""一份最小的评测跑批：用例 -> 运行 -> 指标 -> 区间 -> 门禁。

不联网。40 条用例，两个配置各跑一遍，判定候选版能不能发。

用例与"模型"都是脚本化的：每条用例的通过与否由 (配置, 用例 id) 的哈希决定，
这样同一配置重复跑结果稳定，不同配置之间又有差异。真实系统里这一步是调用
待评测的 agent，其余（区间、门禁、报告）完全一样。

用法：
    python code/eval/run_eval.py
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

Z = 1.96
REGRESSION_PP = 0.02
COST_RULE = 0.05


@dataclass
class Case:
    cid: str
    kind: str          # 正例 / 负例 / 边界


CASES = (
    [Case(f"pos-{i:02d}", "正例") for i in range(1, 23)]
    + [Case(f"neg-{i:02d}", "负例") for i in range(1, 10)]
    + [Case(f"edge-{i:02d}", "边界") for i in range(1, 10)]
)


def run(config: str, case: Case) -> bool:
    """脚本化的'运行'：同一 (配置, 用例) 结果稳定。"""
    h = hashlib.sha1(f"{config}:{case.cid}".encode()).digest()[0]
    threshold = {"baseline": 40, "candidate": 10, "risky": 81}[config]
    return h >= threshold


CONFIGS = ("baseline", "candidate", "risky")


def wilson(k: int, n: int) -> tuple[float, float]:
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return center - half, center + half


def diff_ci(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    p1, p2 = k1 / n1, k2 / n2
    d = p2 - p1
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return d, d - Z * se, d + Z * se


def main() -> None:
    results: dict[str, list[tuple[Case, bool]]] = {}
    for config in CONFIGS:
        results[config] = [(c, run(config, c)) for c in CASES]

    print(f"=== 1. 三个配置各跑 {len(CASES)} 条 ===")
    for config, rows in results.items():
        k = sum(1 for _, ok in rows if ok)
        n = len(rows)
        lo, hi = wilson(k, n)
        by_kind = {}
        for c, ok in rows:
            by_kind.setdefault(c.kind, [0, 0])
            by_kind[c.kind][0] += 1 if ok else 0
            by_kind[c.kind][1] += 1
        print(f"  {config:<10}{k}/{n} = {k / n:.0%}  区间 [{lo:.1%}, {hi:.1%}]")
        for kind, (ok, total) in by_kind.items():
            print(f"    {kind}：{ok}/{total} = {ok / total:.0%}")

    print()
    print("=== 2. 与基线的差异 ===")
    k1 = sum(1 for _, ok in results["baseline"] if ok)
    n = len(CASES)
    for config in CONFIGS[1:]:
        k2 = sum(1 for _, ok in results[config] if ok)
        d, lo, hi = diff_ci(k1, n, k2, n)
        print(f"  {config:<10}差异 {d * 100:+.1f} 个点，区间 "
              f"[{lo * 100:+.1f}, {hi * 100:+.1f}]  "
              f"{'显著' if lo > 0 or hi < 0 else '不显著'}")

    print()
    print("=== 3. 门禁判定 ===")
    order = {"pass": 0, "warn": 1, "fail": 2}
    for config in CONFIGS[1:]:
        k2 = sum(1 for _, ok in results[config] if ok)
        d, lo, hi = diff_ci(k1, n, k2, n)
        verdicts = []
        if d <= -REGRESSION_PP:
            verdicts.append(("fail", f"质量回归 {d * 100:+.1f} 个点"))
        elif d < 0:
            verdicts.append(("warn", f"质量小幅下降 {d * 100:+.1f} 个点"))
        else:
            verdicts.append(("pass", f"质量未回归（{d * 100:+.1f} 个点）"))
        cost_rel = {"candidate": 0.0, "risky": 0.0}[config]
        verdicts.append(("pass" if cost_rel <= COST_RULE else "fail",
                        f"成本 {cost_rel:+.1%}"))
        final = max(verdicts, key=lambda v: order[v[0]])[0]
        print(f"  [{config}] " + "；".join(f"{k}:{why}" for k, why in verdicts)
              + f" -> {final.upper()}")
        if d > 0:
            print(f"    改善{'已证实' if lo > 0 else '未证实'}："
                  f"{d * 100:+.1f} 个点，区间下界 {lo * 100:+.1f}")

    print()
    print("=== 4. 这个结论有多稳 ===")
    for config in CONFIGS[1:]:
        k2 = sum(1 for _, ok in results[config] if ok)
        _, lo, hi = diff_ci(k1, n, k2, n)
        print(f"  {config:<10}差异区间半宽 {(hi - lo) / 2 * 100:.1f} 个点")
    need = math.ceil(Z * Z * 0.85 * 0.15 / (0.03 ** 2))
    print(f"  想把半宽压到 3 个点，需要约 {need} 条")
    print("  <- 样本不够时，'不显著'不等于'没变'，只等于'看不出来'")


if __name__ == "__main__":
    main()
