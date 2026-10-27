"""温度与 top_p 的作用点不同，用同一分布对照。

不联网。分布是给定的常数，演示两种参数如何改变取样结果。
"""

from __future__ import annotations

import random
from collections import Counter

CANDIDATES = ["A", "B", "C", "D", "E"]
PROBS = [0.60, 0.25, 0.08, 0.05, 0.02]


def apply_temperature(probs: list[float], t: float) -> list[float]:
    if t <= 0:
        i = max(range(len(probs)), key=lambda k: probs[k])
        return [1.0 if k == i else 0.0 for k in range(len(probs))]
    s = [p ** (1.0 / t) for p in probs]
    tot = sum(s)
    return [x / tot for x in s]


def apply_top_p(probs: list[float], p: float) -> list[float]:
    """按概率从高到低保留，直到累积超过 p，其余置零后重新归一化。"""
    order = sorted(range(len(probs)), key=lambda k: -probs[k])
    kept, acc = [], 0.0
    for i in order:
        kept.append(i)
        acc += probs[i]
        if acc >= p:
            break
    out = [0.0] * len(probs)
    for i in kept:
        out[i] = probs[i]
    tot = sum(out)
    return [x / tot if tot else 0.0 for x in out]


def sample(probs: list[float], rng: random.Random) -> int:
    r, acc = rng.random(), 0.0
    for i, p in enumerate(probs):
        acc += p
        if r < acc:
            return i
    return len(probs) - 1


def run(probs: list[float], trials: int = 300) -> Counter:
    rng = random.Random(7)
    return Counter(CANDIDATES[sample(probs, rng)] for _ in range(trials))


def show(label: str, probs: list[float]) -> None:
    counts = run(probs)
    dist = "  ".join(f"{CANDIDATES[i]}:{probs[i]:.2f}" for i in range(len(probs)))
    print(f"  {label}")
    print(f"    分布  {dist}")
    print(f"    300 次 {dict(sorted(counts.items()))}")
    print()


def main() -> None:
    print("原始分布：", "  ".join(f"{CANDIDATES[i]}:{PROBS[i]:.2f}" for i in range(len(PROBS))))
    print()

    print("温度改变相对高低（所有候选都保留）：")
    show("temperature=0.5", apply_temperature(PROBS, 0.5))
    show("temperature=1.5", apply_temperature(PROBS, 1.5))

    print("top_p 改变候选集合（低概率直接消失）：")
    show("top_p=0.90", apply_top_p(PROBS, 0.90))
    show("top_p=0.95", apply_top_p(PROBS, 0.95))

    print("差别：")
    t = apply_temperature(PROBS, 1.5)
    p = apply_top_p(PROBS, 0.90)
    print(f"  温度 1.5：E 的概率从 {PROBS[4]:.2f} 变成 {t[4]:.2f}（还在）")
    print(f"  top_p=0.90：E 的概率变成 {p[4]:.2f}（被排除）")
    print()
    print("温度做的是缩放，top_p 做的是裁剪。")
    print("要保留多样性但不想出现冷门候选，用 top_p；")
    print("要整体降低或提高随机程度，用温度。")


if __name__ == "__main__":
    main()
