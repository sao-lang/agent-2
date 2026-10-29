"""稠密、稀疏、混合：同一批查询上的 recall@k / MRR / nDCG，以及 RRF 的手写版。

用真实组件：BM25Retriever（rank_bm25）、InMemoryVectorStore + bge 嵌入、
EnsembleRetriever（加权 RRF）。首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

import math

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_classic.retrievers import EnsembleRetriever

MODEL = "BAAI/bge-small-zh-v1.5"

DOCS = [
    ("d1", "质量问题导致的退货，往返运费由商家承担。"),
    ("d2", "非质量问题退货，运费由买家承担。"),
    ("d3", "签收后 7 天内可申请无理由退货，商品需保持未拆封。"),
    ("d4", "生鲜类商品不支持无理由退货。"),
    ("d5", "生鲜质量问题请在签收后 24 小时内拍照反馈。"),
    ("d6", "发票可在订单页申请，开票时限为下单后 30 天。"),
    ("d7", "电子发票在申请后 24 小时内发送到绑定邮箱。"),
    ("d8", "商品签收后 15 天内出现降价，可申请补差价。"),
    ("d9", "活动价、优惠券抵扣后的价格不参与价保。"),
    ("d10", "单笔订单满 99 元免运费。"),
    ("d11", "偏远地区不参与包邮，以结算页为准。"),
    ("d12", "收到商品 7 天内可申请换货，需保持未拆封。"),
    ("d13", "退款原路退回，银行卡 3 到 7 个工作日到账。"),
    ("d14", "会员每月有 3 次免运费券。"),
    ("d15", "订单 A1001 已发货，预计 48 小时送达。"),
    ("d16", "无理由退货要求商品未拆封、配件齐全。"),
    ("d17", "生鲜订单按坏果比例退款，不需要寄回。"),
    ("d18", "超过开票时限只能开具消费凭证。"),
    ("d19", "价保每人每单限一次。"),
    ("d20", "会员订单不限金额包邮。"),
    ("d21", "生鲜类商品支持无理由退货，需在签收后 7 天内申请（旧版政策）。"),
    ("d22", "非质量问题退货，往返运费由第三方保险公司承担（试点城市）。"),
    ("d23", "发票需联系客服申请，订单页不提供入口（旧流程）。"),
    ("d24", "会员每月有 1 次免运费券（2024 年权益）。"),
    ("d25", "订单 A1000 已取消，退款处理中。"),
    ("d26", "换货不受 7 天限制，随时可申请（特殊品类）。"),
    ("d27", "生鲜类商品不支持换货，只能退货退款。"),
]

QUERIES = [
    ("生鲜坏了怎么退", {"d4", "d5", "d17"}),
    ("发票多久能开", {"d6", "d7"}),
    ("买完降价了怎么办", {"d8", "d9", "d19"}),
    ("免运费要满多少", {"d10", "d20"}),
    ("订单 A1001 到哪了", {"d15"}),
    ("退款什么时候到账", {"d13"}),
    ("换货要几天内申请", {"d12"}),
    ("会员有什么优惠", {"d14", "d20"}),
    ("偏远地区包邮吗", {"d11"}),
    ("退货需要拆封吗", {"d3", "d16"}),
]


def recall_at(ranked: list[str], rel: set[str], k: int) -> float:
    return len(set(ranked[:k]) & rel) / len(rel)


def mrr_at(ranked: list[str], rel: set[str], k: int) -> float:
    for i, doc_id in enumerate(ranked[:k], 1):
        if doc_id in rel:
            return 1 / i
    return 0.0


def ndcg_at(ranked: list[str], rel: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 1) for i, d in enumerate(ranked[:k], 1) if d in rel)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(rel), k) + 1))
    return dcg / ideal if ideal else 0.0


def evaluate(name: str, results: list[list[str]], k: int = 5) -> None:
    r = sum(recall_at(ids, rel, k) for ids, (_, rel) in zip(results, QUERIES)) / len(QUERIES)
    m = sum(mrr_at(ids, rel, k) for ids, (_, rel) in zip(results, QUERIES)) / len(QUERIES)
    n = sum(ndcg_at(ids, rel, k) for ids, (_, rel) in zip(results, QUERIES)) / len(QUERIES)
    print(f"  {name:<26} recall@{k} {r:.2f}   MRR@{k} {m:.2f}   nDCG@{k} {n:.2f}")


def rrf(rankings: list[list[str]], weights: list[float], c: int = 60) -> list[str]:
    """手写 RRF：每条结果 1/(c + rank) 累加，与分数绝对值无关。"""
    scores: dict[str, float] = {}
    for ranking, w in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, 1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (c + rank)
    return sorted(scores, key=lambda d: -scores[d])


def main() -> None:
    docs = [Document(page_content=text, metadata={"id": i}) for i, text in docs_iter()]
    emb = HuggingFaceEmbeddings(model_name=MODEL,
                                encode_kwargs={"normalize_embeddings": True})
    store = InMemoryVectorStore(embedding=emb)
    store.add_documents(docs)

    dense = store.as_retriever(search_kwargs={"k": 5})
    bm25_raw = BM25Retriever.from_documents(docs, k=5)          # 默认按空格切词
    bm25 = BM25Retriever.from_documents(docs, k=5,
                                        preprocess_func=list)   # 按字符切，中文可用

    print("=== 1. 三种检索在同一批查询上的指标（k=5）===")
    dense_res, bm25_res = [], []
    for q, _ in QUERIES:
        dense_res.append([d.metadata["id"] for d in dense.invoke(q)])
        bm25_res.append([d.metadata["id"] for d in bm25_raw.invoke(q)])

    evaluate("稠密（bge-small）", dense_res)
    evaluate("稀疏（BM25，未分词）", bm25_res)

    char_res = [[d.metadata["id"] for d in bm25.invoke(q)] for q, _ in QUERIES]
    evaluate("稀疏（BM25，按字符切）", char_res)

    for weights, tag in [([0.5, 0.5], "混合 0.5/0.5"),
                         ([0.8, 0.2], "混合 0.8/0.2（偏稀疏）"),
                         ([0.2, 0.8], "混合 0.2/0.8（偏稠密）")]:
        ens = EnsembleRetriever(retrievers=[bm25, dense], weights=weights, k=5)
        res = [[d.metadata["id"] for d in ens.invoke(q)] for q, _ in QUERIES]
        evaluate(tag, res)

    print()
    print("=== 2. 手写 RRF 与加权求和的差别 ===")
    q = "订单 A1001 到哪了"
    b = [d.metadata["id"] for d in bm25.invoke(q)]
    v = [d.metadata["id"] for d in dense.invoke(q)]
    print(f"  BM25 排名   {b}")
    print(f"  稠密排名    {v}")
    print(f"  RRF 等权    {rrf([b, v], [0.5, 0.5])}")
    print(f"  RRF 偏稀疏  {rrf([b, v], [0.8, 0.2])}")


def docs_iter():
    for i, text in DOCS:
        yield i, text


if __name__ == "__main__":
    main()

