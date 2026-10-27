"""温度对输出稳定性的影响。用固定概率分布演示取样结果。

不联网。这不是调用模型，是按一个给定的候选分布按不同温度取样。

分布本身（下面 PROBS）是演示用的常数。真实模型每一步的分布由模型算出，
这里只关心"温度如何改变取样结果"这件事。
"""

from __future__ import annotations

import random
from collections import Counter

# 某一步的候选 token 与原始概率（已归一化）
CANDIDATES = ["7天", "7日", "一周", "七天", "3天"]
PROBS = [0.50, 0.22, 0.15, 0.10, 0.03]


def apply_temperature(probs: list[float], temperature: float) -> list[float]:
    """温度 <1 时分布更尖，>1 时更平。返回归一化后的概率。"""
    if temperature <= 0:
        # 温度 0 等价于取最大概率的那一个（贪心）
        idx = max(range(len(probs)), key=lambda i: probs[i])
        return [1.0 if i == idx else 0.0 for i in range(len(probs))]

    scaled = [p ** (1.0 / temperature) for p in probs]
    total = sum(scaled)
    return [s / total for s in scaled]


def sample(probs: list[float], rng: random.Random) -> int:
    r = rng.random()
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if r < acc:
            return i
    return len(probs) - 1


def run(temperature: float, trials: int = 200, seed: int = 42) -> Counter:
    probs = apply_temperature(PROBS, temperature)
    rng = random.Random(seed)
    return Counter(CANDIDATES[sample(probs, rng)] for _ in range(trials))


def main() -> None:
    print("原始分布：")
    for t, p in zip(CANDIDATES, PROBS):
        print(f"  {t:<6} {p:.2f}")
    print()

    for temperature in (0.0, 0.7, 1.0, 1.5):
        probs = apply_temperature(PROBS, temperature)
        counts = run(temperature, trials=200)
        dist = "  ".join(f"{t}:{probs[i]:.2f}" for i, t in enumerate(CANDIDATES))
        print(f"=== temperature = {temperature} ===")
        print(f"  调整后分布  {dist}")
        print(f"  200 次取样  {dict(counts)}")
        top = counts.most_common(1)[0]
        print(f"  最高频结果  {top[0]} 出现 {top[1]}/200 次")
        print()

    print("同一输入、同一分布，温度不同，结果的分散程度不同：")
    t0 = run(0.0, 200).most_common(1)[0][1]
    t15 = run(1.5, 200).most_common(1)[0][1]
    print(f"  温度 0    最高频结果占 {t0}/200")
    print(f"  温度 1.5  最高频结果占 {t15}/200")
    print()
    print("温度 0 时每次结果相同，温度的升高让低概率候选出现的机会变大。")
    print("对需要解析字段的输出，这是不稳定来源之一。")


if __name__ == "__main__":
    main()
