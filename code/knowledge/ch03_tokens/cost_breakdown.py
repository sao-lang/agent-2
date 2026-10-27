"""一次多轮任务的成本拆解。

不联网。用一组 usage 记录演示：钱花在哪一环，输入与输出的差价有多大。
所有单价是演示用的相对值，不是任何厂商的真实价格。
"""

from __future__ import annotations

from dataclasses import dataclass

# 演示用单价（元 / 千 token），输入与输出不同价
PRICE_IN = 0.002
PRICE_OUT = 0.008
PRICE_CACHE = 0.0005   # 命中缓存的输入


@dataclass
class Call:
    round: int
    prompt: int
    completion: int
    cached: int = 0        # 其中命中缓存的部分


# 一个四轮任务的记录：每轮 prompt 包含全部历史，所以逐轮增长
CALLS = [
    Call(1, prompt=800, completion=120),
    Call(2, prompt=1400, completion=180, cached=800),
    Call(3, prompt=1900, completion=150, cached=1400),
    Call(4, prompt=2200, completion=90, cached=1900),
]


def cost(c: Call) -> float:
    billed_in = c.prompt - c.cached
    return (
        billed_in / 1000 * PRICE_IN
        + c.cached / 1000 * PRICE_CACHE
        + c.completion / 1000 * PRICE_OUT
    )


def main() -> None:
    print(f"单价：输入 {PRICE_IN}/千，输出 {PRICE_OUT}/千，缓存命中 {PRICE_CACHE}/千")
    print()
    print(f"{'轮次':>4}{'prompt':>9}{'其中缓存':>10}{'completion':>12}{'成本':>10}")
    print("-" * 47)

    total = 0.0
    for c in CALLS:
        x = cost(c)
        total += x
        print(f"{c.round:>4}{c.prompt:>9}{c.cached:>10}{c.completion:>12}{x:>10.6f}")

    in_tokens = sum(c.prompt for c in CALLS)
    out_tokens = sum(c.completion for c in CALLS)
    cached = sum(c.cached for c in CALLS)

    print("-" * 47)
    print(f"{'合计':>4}{in_tokens:>9}{cached:>10}{out_tokens:>12}{total:>10.6f}")

    print()
    print("拆解：")
    no_cache_in = (in_tokens - cached) / 1000 * PRICE_IN
    cache_in = cached / 1000 * PRICE_CACHE
    out_cost = out_tokens / 1000 * PRICE_OUT
    print(f"  输入（未命中）  {no_cache_in:>9.6f}  {no_cache_in/total:>6.1%}")
    print(f"  输入（命中缓存）{cache_in:>9.6f}  {cache_in/total:>6.1%}")
    print(f"  输出            {out_cost:>9.6f}  {out_cost/total:>6.1%}")
    print()
    print(f"输出 token 只占总量 {out_tokens/(in_tokens+out_tokens):.1%}，")
    print(f"却占了成本的 {out_cost/total:.1%}。")
    print()
    print("两个观察：")
    print("  1. 每轮 prompt 都包含全部历史，所以输入 token 逐轮累加。")
    print("  2. 缓存只能命中不变的前缀；历史一长，前缀就越长，命中价值越大。")

    print()
    print("如果完全不用缓存：")
    no_cache_total = in_tokens / 1000 * PRICE_IN + out_tokens / 1000 * PRICE_OUT
    print(f"  {no_cache_total:.6f}，比实际高 {(no_cache_total/total - 1):.0%}")


if __name__ == "__main__":
    main()
