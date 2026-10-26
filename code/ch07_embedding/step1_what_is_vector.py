"""第 7 章 step1：向量到底是什么——用 20 行看清"把词变成坐标"（离线）。

运行：
    python code/ch07_embedding/step1_what_is_vector.py

上一级的痛点（第 6 章）：你能让模型稳定输出 JSON 了。但用户问"退货政策"，
                         而文档里写的是"退货规则"——关键词搜不到，怎么办？

这一级做什么：先不用任何模型，用**手写的词袋向量**建立三件直觉：

  ① 向量 = 一串数字 = 空间里的一个点
  ② 相似的文本 → 向量方向接近 → 余弦相似度高
  ③ **但词袋向量只看"词有没有出现"，看不懂"意思"** ← 这就是后面要嵌入模型的原因

关键：这一级**一定要先看清"朴素方法哪里不够"**，
     否则你会以为嵌入模型是黑魔法。
"""
from __future__ import annotations

import math
from collections import Counter


def bag_of_words(text: str, vocab: list[str]) -> list[float]:
    """最朴素的向量化：每个词出现几次。

    这就是"向量"最原始的样子——**一串数**。
    """
    tokens = text.split()
    c = Counter(tokens)
    return [float(c.get(w, 0)) for w in vocab]


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度：只看向量方向，不看长度。

    为什么不用欧氏距离？因为"长文档"和"短文档"讲同一件事时，
    长度差很多但意思一样——欧氏距离会把它们判成不相似。
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


DOCS = [
    "退货 政策 七天 无理由",
    "退货 规则 七日 无理由",
    "换货 流程 质量 问题",
    "物流 配送 时效",
    "退款 到账 时间",
]

QUERIES = [
    ("退货 政策", "和文档 1 几乎同词"),
    ("退货 规则", "和文档 2 同词，和文档 1 差一个词"),
    ("不想要 了 能 退 吗", "**同义但不同词**（人类一看就懂，词袋看不懂）"),
    ("钱 什么 时候 到账", "同义：退款到账"),
]


def main() -> None:
    vocab = sorted({w for d in DOCS for w in d.split()})
    print("=" * 88)
    print(f"词表（{len(vocab)} 个词）：{vocab}")
    print("=" * 88)

    print("\n每个文档的向量（就是这些数字）：")
    doc_vecs = {}
    for i, d in enumerate(DOCS, 1):
        v = bag_of_words(d, vocab)
        doc_vecs[d] = v
        shown = ", ".join(f"{x:.0f}" for x in v)
        print(f"  d{i} [{shown}]  ← {d}")

    print("\n" + "=" * 88)
    print("检索：给一个查询，算它和每个文档的余弦相似度")
    print("=" * 88)

    for q, note in QUERIES:
        qv = bag_of_words(q, vocab)
        scores = sorted(
            ((cosine(qv, doc_vecs[d]), d) for d in DOCS), reverse=True
        )
        print(f"\n查询：「{q}」   （{note}）")
        for s, d in scores[:3]:
            bar = "█" * int(s * 30)
            print(f"  {s:.3f} {bar:<30} {d}")

    print("\n" + "=" * 88)
    print("关键：第 3 个查询为什么失败")
    print("=" * 88)
    q3 = "不想要 了 能 退 吗"
    qv3 = bag_of_words(q3, vocab)
    print(f"  查询：「{q3}」")
    print("  它的向量全是 0 吗？不是——'退' 这个词不在词表里，但 '了'/'能'/'吗' 也不在。")
    print(f"  实际向量：{qv3}")
    print(f"  → 和所有文档的相似度都是 {cosine(qv3, doc_vecs[DOCS[0]]):.3f}")
    print()
    print("  **词袋的根本缺陷：它只数'词有没有原样出现'。**")
    print("  所以：")
    print("    · '退款' 和 '退钱' 完全不相关（字面不同）")
    print("    · '退货政策' 和 '退款政策' 相关度也不高（只共享一个词）")
    print("    · 同义词、近义词、换一种说法 → **全部失效**")

    print("\n" + "=" * 88)
    print("对比：第 1、2 个查询为什么成功")
    print("=" * 88)
    for q, _ in QUERIES[:2]:
        qv = bag_of_words(q, vocab)
        scores = sorted(((cosine(qv, doc_vecs[d]), d) for d in DOCS), reverse=True)
        print(f"  「{q}」 → 最相似：{scores[0][1]}（{scores[0][0]:.3f}）")
    print()
    print("  因为它和文档**共享了词**。这就是'关键词检索'的本质。")
    print("  在术语一致的场景（代码、型号、法规条款号）里，关键词检索其实很好用——")
    print("  **不要一上来就换向量检索**（第 11 章会给混合检索）。")

    print("\n" + "=" * 88)
    print("结论：向量化的三步进化")
    print("=" * 88)
    print("  ① 词袋（本节）：数词出现几次 → 只能处理'用词一致'")
    print("  ② TF-IDF：给罕见词更高权重 → 好一些，但仍是字面匹配")
    print("  ③ **嵌入模型**：让模型学'意思' → 同义词/换说法也能匹配（step2）")
    print()
    print("  但 ①③ 有一个共同点：**都是把文本变成一串数字，然后用余弦算远近。**")
    print("  向量检索的全部数学，就是这一件事。复杂的地方在'怎么得到好向量'。")

    # 断言：同词查询必须有分（0.7 而不是 1.0，因为 d1 有 4 个词、查询只有 2 个）
    assert cosine(bag_of_words("退货 政策", vocab), doc_vecs[DOCS[0]]) > 0.7
    assert cosine(bag_of_words("不想要 了 能 退 吗", vocab), doc_vecs[DOCS[0]]) == 0.0


if __name__ == "__main__":
    main()
