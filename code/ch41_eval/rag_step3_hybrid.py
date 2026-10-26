"""第 29 章 step3：只加一个概念 —— 混合检索（向量 + 关键词，用 RRF 合并）。

运行：
    python code/ch41_eval/rag_step3_hybrid.py

上一级的痛点：recall@1 明显低于 recall@5。答案明明在候选里，就是排不到第一。
这一级做什么：把"两路召回"的结果融合，让精确词（数字/电话/型号）也能排上来。

为什么需要两路？
  向量检索擅长"意思相近"：查"耳机有杂音"能命中"电流声"。
  但它不擅长"一模一样"：查"400-800-1234"，它可能觉得"客服电话"更像。

为什么要 RRF 而不是分数直接相加？
  向量相似度是 0~1，BM25 分数是 0~30。量纲不同直接加 = 用一个指标淹没另一个。
  RRF 只看**排名**，天然免疫量纲问题。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.hybrid_search import rrf_fuse  # noqa: E402
from common.rag_eval import EvalCase, load_cases, retrieval_metrics  # noqa: E402
from common.retrieval import BM25, Index, hash_embed, split_by_heading  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")


def build() -> Index:
    idx = Index(embed=hash_embed)
    texts = split_by_heading(DOC, max_chars=400)
    metas = []
    for t in texts:
        m = re.search(r"###\s*(\d+)\.(\d+)", t)
        metas.append({"sections": [f"{m.group(1)}.{m.group(2)}"] if m else []})
    idx.add(texts, metas)
    return idx


def gold_ids_for(case: EvalCase, idx: Index) -> list[str]:
    return [c.id for c in idx.chunks if case.anchor and case.anchor in c.meta.get("sections", [])]


def dense_ids(idx: Index, q: str, n: int) -> list[str]:
    return [c.id for c, _ in idx.search(q, k=n)]


def sparse_ids(idx: Index, bm25: BM25, q: str, n: int) -> list[str]:
    scores = bm25.scores(q)
    order = scores.argsort()[::-1][:n]
    return [idx.chunks[i].id for i in order]


def evaluate(idx: Index, bm25: BM25, cases: list[EvalCase], mode: str) -> tuple[float, float, float]:
    rows = []
    for case in cases:
        if not case.anchor:
            continue
        if mode == "dense":
            got = dense_ids(idx, case.question, 5)
        elif mode == "sparse":
            got = sparse_ids(idx, bm25, case.question, 5)
        elif mode == "hybrid":
            # ① 两路各取 20 个候选  ② RRF 融合  ③ 取前 5
            fused = rrf_fuse(
                [dense_ids(idx, case.question, 20), sparse_ids(idx, bm25, case.question, 20)],
                k=60,
            )
            got = [cid for cid, _ in fused][:5]
        else:
            raise ValueError(mode)
        recall, mrr = retrieval_metrics(got, gold_ids_for(case, idx), ks=(1, 3, 5))
        rows.append((recall, mrr))

    n = len(rows)
    return (
        sum(1 for r, _ in rows if r[1]) / n,
        sum(1 for r, _ in rows if r[5]) / n,
        sum(m for _, m in rows) / n,
    )


def main() -> None:
    idx = build()
    bm25 = BM25(idx.all_texts())
    cases = load_cases(ROOT / "evals" / "rag_cases.json")

    print("=" * 74)
    print("只加一个概念：把两路召回的结果交给 RRF 合并")
    print("=" * 74)
    print(f"{'方案':<26}{'recall@1':>10}{'recall@5':>10}{'mrr':>8}")
    print("-" * 56)

    results = {}
    for mode, label in [("dense", "① 纯向量"), ("sparse", "② 纯 BM25"), ("hybrid", "③ 向量 + BM25 + RRF")]:
        r1, r5, mrr = evaluate(idx, bm25, cases, mode)
        results[mode] = (r1, r5, mrr)
        print(f"{label:<26}{r1:>10.3f}{r5:>10.3f}{mrr:>8.3f}")

    print("\n" + "=" * 74)
    print("为什么两路都要（看具体样本）")
    print("=" * 74)
    for q in ("客服电话是多少？", "耳塞网罩堵了怎么清理？"):
        case = next(c for c in cases if c.question == q)
        gold = gold_ids_for(case, idx)[0]
        d20 = dense_ids(idx, q, 20)
        s20 = sparse_ids(idx, bm25, q, 20)
        fused = rrf_fuse([d20, s20], k=60)
        print(f"\n  问题：{q}")
        print(f"    向量 top-3 ：{d20[:3]}")
        print(f"    BM25 top-3 ：{s20[:3]}")
        print(f"    RRF  top-3 ：{[cid for cid, _ in fused][:3]}")
        print(f"    答案所在   ：{gold}")
        print(f"      ^ 单看一路：向量排第 {d20.index(gold) + 1}，BM25 排第 {s20.index(gold) + 1}")
        print("        两路都把它放进了候选，RRF 就会把「两路都靠前」的文档顶上去")

    print("\n" + "=" * 74)
    print("这一级解决了什么")
    print("=" * 74)
    before, after = results["dense"], results["hybrid"]
    print(f"  recall@1：{before[0]:.3f} → {after[0]:.3f}（{after[0] - before[0]:+.3f}）")
    print(f"  recall@5：{before[1]:.3f} → {after[1]:.3f}（{after[1] - before[1]:+.3f}）")
    print(f"  mrr     ：{before[2]:.3f} → {after[2]:.3f}（{after[2] - before[2]:+.3f}）")
    print("\n  它解决的是「排不准」，但**没解决「找不到」**：")
    print("  如果分块把一句话切成了两半，两路检索都救不回来——下一级换个切法。")


if __name__ == "__main__":
    main()
