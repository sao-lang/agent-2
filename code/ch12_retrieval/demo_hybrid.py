"""第 12 章示例：检索优化的每一步收益（不需要 API）。

运行：
    python code/ch12_retrieval/demo_hybrid.py

对照四档：
  dense  → 只向量
  hybrid → +BM25 +RRF
  rerank → +重排
  full   → +多查询改写

同时输出 recall@1 / recall@5 / MRR，让你看清"每一步到底换来什么"。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.hybrid_search import RetrievalPipeline, rrf_fuse  # noqa: E402
from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402

DOC = (Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md").read_text(encoding="utf-8")

# (问题, 答案关键词, 难度标记)
# 特意混入两类"向量检索容易失败"的问题：
#   · 短查询（"运费"）—— 向量表示太泛
#   · 术语/数字（"400-800-1234"、"48 小时"）—— 稀疏检索更擅长
CASES = [
    ("无理由退货几天内可以申请？", "7 天"),
    ("蓝牙耳机右耳有电流声怎么办？", "编解码"),
    ("换新流程要多久？", "5 到 7 个工作日"),
    ("运费谁承担？", "往返运费由商家承担"),
    ("怎么转人工客服？", "转人工"),
    ("会员有什么优惠？", "满 300 减 30"),
    ("价格保护几天内有效？", "15 天"),
    ("发票多久能开出来？", "7 个工作日"),
    ("客服电话是多少？", "400-800-1234"),
    ("新机多久发出？", "48 小时"),
    ("耳塞网罩堵了怎么清理？", "软毛刷"),
    ("用了优惠券退货会返还吗？", "不返还"),
]


def metrics(pipeline: RetrievalPipeline, k_list=(1, 5)) -> dict:
    hits = {k: 0 for k in k_list}
    mrr = 0.0
    for q, keyword in CASES:
        results = pipeline.search(q, k=5)
        texts = [pipeline.index.chunks[[c.id for c in pipeline.index.chunks].index(cid)].text
                 for cid, _ in results]
        found_at = None
        for rank, t in enumerate(texts, 1):
            if keyword in t:
                found_at = rank
                break
        for k in k_list:
            if found_at and found_at <= k:
                hits[k] += 1
        if found_at:
            mrr += 1.0 / found_at
    n = len(CASES)
    return {f"recall@{k}": hits[k] / n for k in k_list} | {"mrr": mrr / n}


def main() -> None:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=400))

    print(f"语料：{len(DOC)} 字符，{len(idx.chunks)} 块   问题：{len(CASES)} 个\n")

    print(f"{'模式':<10}{'recall@1':>10}{'recall@5':>10}{'MRR':>8}")
    print("-" * 40)
    base = None
    for mode in ["dense", "hybrid", "rerank", "full"]:
        p = RetrievalPipeline(index=idx, mode=mode)
        m = metrics(p)
        if base is None:
            base = m
        print(f"{mode:<10}{m['recall@1']:>9.0%}{m['recall@5']:>10.0%}{m['mrr']:>8.3f}")

    print("\n" + "=" * 70)
    print("RRF 融合到底在做什么")
    print("=" * 70)
    dense = ["c3", "c1", "c7", "c2"]
    sparse = ["c7", "c3", "c9", "c1"]
    print(f"  向量排序：{dense}")
    print(f"  BM25排序：{sparse}")
    print("  融合结果（RRF，k=60）：")
    for doc_id, score in rrf_fuse([dense, sparse]):
        print(f"    {doc_id}  {score:.5f}")
    print("\n  注意 c3 和 c7：两边都在前列的，融合后位置最高。")
    print("  这就是 RRF 的价值——**共识优先**，不需要调权重。")

    print("\n" + "=" * 70)
    print("哪类问题检索最容易失败")
    print("=" * 70)
    p = RetrievalPipeline(index=idx, mode="dense")
    for q, keyword in CASES:
        res = p.search(q, k=5)
        ids = [c.id for c in idx.chunks]
        texts = [idx.chunks[ids.index(cid)].text for cid, _ in res]
        rank = next((i for i, t in enumerate(texts, 1) if keyword in t), None)
        if rank != 1:
            print(f"  {'排名第 ' + str(rank) if rank else '未命中':<10} {q}")

    print("\n  👉 短查询（'运费'）和数字查询（'400-800-1234'）是向量检索的弱项，")
    print("     混合检索和重排就是专门补这两块的。")

    print("\n" + "=" * 70)
    print("⚠️ 关于这份报告的可信度")
    print("=" * 70)
    print("  · 语料只有 889 字、12 个问题，指标波动大，只用于展示方法")
    print("  · 哈希嵌入的语义能力弱，绝对数值偏低")
    print("  · 换成你的真实语料 + 真嵌入模型，再把这张表跑一遍——那才是你的基线")


if __name__ == "__main__":
    main()
