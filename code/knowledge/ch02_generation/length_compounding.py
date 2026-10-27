"""温度对长文本的累积影响：单步概率不变，整段一致的概率指数下降。

不联网。用固定分布演示"每一步看起来都很稳，整段却很难两次相同"。
"""

from __future__ import annotations

import random

# 每一步的分布：同一个候选占多数，其余分散
STEP_PROBS = [0.70, 0.15, 0.10, 0.05]
LABELS = ["A", "B", "C", "D"]


def apply_temperature(probs: list[float], t: float) -> list[float]:
    if t <= 0:
        i = max(range(len(probs)), key=lambda k: probs[k])
        return [1.0 if k == i else 0.0 for k in range(len(probs))]
    s = [p ** (1.0 / t) for p in probs]
    tot = sum(s)
    return [x / tot for x in s]


def one_sequence(probs: list[float], length: int, rng: random.Random) -> str:
    out = []
    for _ in range(length):
        r, acc = rng.random(), 0.0
        for i, p in enumerate(probs):
            acc += p
            if r < acc:
                out.append(LABELS[i])
                break
        else:
            out.append(LABELS[-1])
    return "".join(out)


def same_rate(probs: list[float], length: int, trials: int = 200) -> float:
    """跑 trials 次，统计与第一次完全相同的有几次。"""
    rng = random.Random(11)
    first = one_sequence(probs, length, rng)
    same = sum(1 for _ in range(trials - 1) if one_sequence(probs, length, rng) == first)
    return same / (trials - 1)


def main() -> None:
    print("每步分布：", "  ".join(f"{LABELS[i]}:{STEP_PROBS[i]:.2f}" for i in range(len(STEP_PROBS))))
    print("（最高频候选占 70%，单看一步很稳）")
    print()

    print(f"{'temperature':>12}{'步数':>8}{'两次完全相同':>14}")
    print("-" * 36)

    for t in (0.3, 0.7, 1.0):
        probs = apply_temperature(STEP_PROBS, t)
        for length in (1, 5, 20, 50):
            rate = same_rate(probs, length)
            print(f"{t:>12}{length:>8}{rate:>13.1%}")
        print()

    print("读法：")
    print("  温度 0.3，单步最高频占 {:.0%}，".format(apply_temperature(STEP_PROBS, 0.3)[0]))
    print("  但 50 步全对的概率是它连乘 50 次，几乎没有。")
    print()
    print("结论：")
    print("  '单步稳定'不等于'整段稳定'。")
    print("  输出越长，两次完全相同的概率越低。")
    print("  要判断改动是否有效，必须比较多次运行，不能各跑一次。")


if __name__ == "__main__":
    main()
