"""第 2 章 step3：采样参数对结构化输出的影响（离线可运行）。

运行：
    python code/ch02_generation/step3_sampling.py

本文件用可复现的概率表模拟两个位置的候选分布，
展示温度如何改变「产出合法结构」的概率。

所有数值来自下方的候选表与本文件的采样逻辑，
运行本脚本即可得到相同结果（固定种子）。
"""

from __future__ import annotations

import random
import sys


# 位置 A：字段名。合法值是 "days"
# 位置 B：字段值。合法值是 7 或 15
CANDIDATES = {
    "A": [("days", 0.70), ("time", 0.20), ("duration", 0.10)],
    "B": [("7", 0.65), ("15", 0.25), ("seven", 0.10)],
}

LEGAL = {"A": {"days"}, "B": {"7", "15"}}


def sample(dist: list[tuple[str, float]], temperature: float, rng: random.Random) -> str:
    if temperature <= 0:
        return max(dist, key=lambda x: x[1])[0]
    weights = [(v, p ** (1.0 / temperature)) for v, p in dist]
    total = sum(w for _, w in weights)
    r = rng.random() * total
    acc = 0.0
    for value, w in weights:
        acc += w
        if r <= acc:
            return value
    return weights[-1][0]


def run(temperature: float, trials: int = 2000, seed: int = 42) -> dict:
    """两个位置都合法，整体结构才算合法。"""
    rng = random.Random(seed)
    both_legal = 0
    a_legal = 0
    b_legal = 0
    for _ in range(trials):
        a = sample(CANDIDATES["A"], temperature, rng)
        b = sample(CANDIDATES["B"], temperature, rng)
        if a in LEGAL["A"]:
            a_legal += 1
        if b in LEGAL["B"]:
            b_legal += 1
        if a in LEGAL["A"] and b in LEGAL["B"]:
            both_legal += 1
    return {
        "a": a_legal / trials,
        "b": b_legal / trials,
        "both": both_legal / trials,
    }


def main() -> None:
    print("=" * 82)
    print("① 两个位置的候选分布")
    print("=" * 82)
    for pos, dist in CANDIDATES.items():
        legal = LEGAL[pos]
        print(f"\n  位置 {pos}（合法值：{', '.join(sorted(legal))}）")
        for value, p in dist:
            mark = "合法" if value in legal else "非法"
            print(f"    {value:<10}{p:.2f}   {mark}")

    print()
    print("=" * 82)
    print("② 不同温度下，一次生成整体合法的比例")
    print("=" * 82)
    print(f"  {'温度':<8}{'位置A合法':<12}{'位置B合法':<12}{'整体合法'}")
    print("  " + "-" * 74)
    for t in (0.0, 0.3, 0.7, 1.0, 1.5):
        r = run(t)
        print(f"  {t:<8}{r['a']:.3f}       {r['b']:.3f}       {r['both']:.3f}")

    print()
    print("  注：以上比例由本文件在 2000 次采样下统计，固定种子 42。")

    print()
    print("=" * 82)
    print("③ 为什么整体合法率低于单点合法率")
    print("=" * 82)
    print("  结构合法要求每个位置都对。任一位置出错，整条输出作废。")
    print("  位置越多，整体合法率下降越快。")
    print()
    trials = 3
    per = 0.9
    print(f"  假设每个位置合法的概率为 {per}，共 {trials} 个位置：")
    print(f"    整体合法率 = {per} ^ {trials} = {per ** trials:.3f}")
    for n in range(1, 8):
        print(f"    {n} 个位置 → {per ** n:.3f}")

    print()
    print("=" * 82)
    print("④ 结论")
    print("=" * 82)
    print("  1. 温度降低，非法取值被选中的概率下降")
    print("  2. 结构化输出包含多个位置，整体合法率是各位置的乘积")
    print("  3. 位置越多，对温度越敏感")
    print("  4. 低温度不能保证 100% 合法，仍需校验与重试")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
