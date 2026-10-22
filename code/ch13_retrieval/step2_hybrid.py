"""第 13 章 · 第 2 级：混合检索 —— 向量通道 + 词面通道，用 RRF 融合。

运行：
    python code/ch13_retrieval/step2_hybrid.py

新增的两个概念：
  · **BM25**：按词面匹配的经典算法。它是 1994 年的，但今天依然不可替代。
  · **RRF（倒数排名融合）**：只看排名、不看分数，天然免疫量纲问题。

为什么不能把两边的分数直接相加？
  向量余弦相似度在 0~1 之间，BM25 分数可以到 30 —— 相加等于让 BM25 完全主导。
"""
from __future__ import annotations

from pathlib import Path

from step1_dense_failures import CASES, DenseIndex, bm25_scores, split_by_heading

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"


def rank_of(scores: list[float]) -> list[int]:
    """分数 → 排名（0 是第一名）。同分时保持原始顺序，保证可复现。"""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """RRF：score(d) = Σ 1 / (k + rank_i(d))。

    k 的作用是**削弱第一名与第二名的差距**，避免单个通道的噪声过度主导。
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)
    idx = DenseIndex(chunks)

    print("=" * 84)
    print("第 2 级：混合检索（Dense + BM25 + RRF）")
    print("=" * 84)
    print(f"  语料 {len(chunks)} 块   问题 {len(CASES)} 个\n")

    print(f"{'问题':<24}{'Dense':<10}{'BM25':<10}{'混合':<10}")
    print("-" * 84)

    totals = {"dense": 0, "bm25": 0, "hybrid": 0}
    for q, key, kind in CASES:
        # Dense 排名：用 cosine 全量排序
        qv = idx.search(q, k=len(chunks))
        dense_order = [i for _, i in qv]
        d_pos = next((r + 1 for r, i in enumerate(dense_order) if key in chunks[i]), None)

        b = bm25_scores(q, chunks)
        bm25_order = rank_of(b)
        b_pos = next((r + 1 for r, i in enumerate(bm25_order) if key in chunks[i]), None)

        fused = rrf_fuse([dense_order, bm25_order])
        h_pos = next((r + 1 for r, (i, _) in enumerate(fused) if key in chunks[i]), None)

        for name, pos in (("dense", d_pos), ("bm25", b_pos), ("hybrid", h_pos)):
            if pos and pos <= 3:
                totals[name] += 1

        fmt = lambda p: f"第{p}位" if p else "未找到"
        print(f"{q:<24}{fmt(d_pos):<10}{fmt(b_pos):<10}{fmt(h_pos):<10}")

    n = len(CASES)
    print("\n  recall@3：")
    for name, v in totals.items():
        print(f"    {name:<8}{v}/{n}  = {v / n:.0%}")

    print("\n" + "=" * 84)
    print("RRF 到底在做什么（一个具体例子）")
    print("=" * 84)
    q = "客服电话多少？"
    qv = idx.search(q, k=len(chunks))
    dense_order = [i for _, i in qv]
    bm25_order = rank_of(bm25_scores(q, chunks))
    print(f"  Dense 前 4：{[chunks[i][:8].replace(chr(10), ' ') for i in dense_order[:4]]}")
    print(f"  BM25  前 4：{[chunks[i][:8].replace(chr(10), ' ') for i in bm25_order[:4]]}")
    print("  融合后前 4：")
    for i, score in rrf_fuse([dense_order, bm25_order])[:4]:
        print(f"    {score:.5f}  {chunks[i][:30].replace(chr(10), ' ')}")

    print("\n  👉 两边都在前列的，融合后最靠前 —— 这叫**共识优先**。")
    print("     不需要调权重，也不受量纲影响。")

    print("\n" + "=" * 84)
    print("为什么不能加权求和")
    print("=" * 84)
    print("  Dense 分数的范围：0 ~ 1（余弦）")
    print(f"  BM25 分数最高可到几十（本例 {max(bm25_scores('客服电话多少？', chunks)):.1f}）")
    print("  直接相加 → BM25 一个通道说了算，等于没做融合。")
    print()
    print("  如果一定要加权，必须先把两边**归一化到同一量纲**，")
    print("  而 RRF 直接绕过了这个问题 —— 这就是它流行的原因。")


if __name__ == "__main__":
    main()
