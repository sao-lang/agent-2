"""第 2 章 step1：续写机制（离线可运行）。

运行：
    python code/ch02_generation/step1_continuation.py

本文件演示模型的基本行为：给定前文，输出下一个 token 的概率分布，
取其中一个，接到前文末尾，重复。

不涉及真实模型。概率表是手工构造的小样本，用于展示机制本身。
"""

from __future__ import annotations

import random
import sys


# 一份极小的"训练语料"：售后文档片段
CORPUS = (
    "签收后七天内可以申请无理由退货。退货需要审核。"
    "定制类商品不适用无理由退货。"
    "已激活的数码产品不适用无理由退货。"
    "签收后十五天内出现质量问题可以换新。换新需要寄回。"
)


def build_table(corpus: str) -> dict[str, dict[str, int]]:
    """统计每个字后面出现过哪些字、各几次。这就是最朴素的"参数"。"""
    table: dict[str, dict[str, int]] = {}
    for a, b in zip(corpus, corpus[1:]):
        table.setdefault(a, {})
        table[a][b] = table[a].get(b, 0) + 1
    return table


def distribution(table: dict[str, dict[str, int]], prefix: str) -> dict[str, float]:
    """把计数归一化成概率。"""
    counts = table.get(prefix, {})
    total = sum(counts.values())
    if total == 0:
        return {}
    return {ch: c / total for ch, c in counts.items()}


def top_k(dist: dict[str, float], k: int = 5) -> list[tuple[str, float]]:
    return sorted(dist.items(), key=lambda x: -x[1])[:k]


def generate(
    table: dict[str, dict[str, int]],
    start: str,
    temperature: float = 0.0,
    steps: int = 40,
    seed: int = 0,
) -> str:
    """按温度采样生成。temperature=0 时取概率最高的那个。"""
    rng = random.Random(seed)
    out = start
    for _ in range(steps):
        dist = distribution(table, out[-1])
        if not dist:
            break
        if temperature <= 0:
            nxt = max(dist, key=lambda c: dist[c])
        else:
            # 温度高的效果：把概率分布拉平
            weights = {c: p ** (1.0 / temperature) for c, p in dist.items()}
            total = sum(weights.values())
            r = rng.random() * total
            acc = 0.0
            nxt = ""
            for c, w in weights.items():
                acc += w
                if r <= acc:
                    nxt = c
                    break
            if not nxt:
                nxt = max(weights, key=lambda c: weights[c])
        out += nxt
        if nxt == "。":
            break
    return out


def main() -> None:
    table = build_table(CORPUS)

    print("=" * 78)
    print("① 语料中「退」后面出现过哪些字")
    print("=" * 78)
    dist = distribution(table, "退")
    for ch, p in top_k(dist, 6):
        print(f"  「退」→「{ch}」   {p:.2f}")

    print()
    print("=" * 78)
    print("② 从同一个起点开始，温度 0 的生成结果")
    print("=" * 78)
    print(f"  起点「签」：{generate(table, '签', temperature=0.0)}")

    print()
    print("=" * 78)
    print("③ 从同一个起点开始，不同温度各生成 5 次")
    print("=" * 78)
    for temp in (0.0, 0.5, 1.0):
        outs = {generate(table, "签", temperature=temp, seed=s) for s in range(5)}
        print(f"\n  温度 {temp}：5 次生成得到 {len(outs)} 种不同结果")
        for o in sorted(outs):
            print(f"    {o}")

    print()
    print("=" * 78)
    print("④ 关键点")
    print("=" * 78)
    print("  1. 每次只算「下一个字」，不知道整句话要表达什么")
    print("  2. 温度 0 时结果固定，因为每一步都取概率最高的那个")
    print("  3. 温度升高，结果开始不一致，因为低概率的字也有机会被选中")
    print("  4. 整个过程没有「检查这句话对不对」的步骤")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
