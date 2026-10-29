"""稀疏与稠密：TF-IDF 与嵌入在同一批文档上的检索结果对比。

两个都是真实实现：TF-IDF 用 scikit-learn，稠密用 bge-small。
首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

import math

from langchain_huggingface import HuggingFaceEmbeddings
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SMALL = "BAAI/bge-small-zh-v1.5"

DOCS = {
    "d1": "质量问题退货，往返运费由商家承担。",
    "d2": "非质量问题退货，运费由买家承担。",
    "d3": "签收后 7 天内可申请无理由退货，需保持未拆封。",
    "d4": "发票可在订单页申请，开票时限为下单后 30 天。",
    "d5": "生鲜类商品不支持无理由退货，质量问题 24 小时内拍照反馈。",
    "d6": "订单 A1001 已发货，预计 48 小时送达。",
}

QUERIES = [
    "A1001 到哪了",              # 编号类，稀疏擅长
    "东西坏了能退吗",            # 换说法，稠密擅长
    "多久能开发票",              # 换说法 + 数量关系
]


def tfidf_rank(query: str, ids: list[str], texts: list[str], k: int = 2):
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 2))
    matrix = vec.fit_transform(texts + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1])[0]
    order = scores.argsort()[::-1][:k]
    return [(ids[i], round(float(scores[i]), 3)) for i in order]


def dense_rank(query: str, ids: list[str], texts: list[str], emb, k: int = 2):
    docs = emb.embed_documents(texts)
    q = emb.embed_query(query)
    scores = [sum(a * b for a, b in zip(q, d)) for d in docs]
    order = sorted(range(len(docs)), key=lambda i: -scores[i])[:k]
    return [(ids[i], round(float(scores[i]), 3)) for i in order]


if __name__ == "__main__":
    ids = list(DOCS)
    texts = list(DOCS.values())
    emb = HuggingFaceEmbeddings(
        model_name=SMALL,
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"文档 {len(texts)} 条，查询 {len(QUERIES)} 条，各自取前 2")
    for q in QUERIES:
        sp = tfidf_rank(q, ids, texts)
        de = dense_rank(q, ids, texts, emb)
        print(f"\n  查询 {q!r}")
        print(f"    TF-IDF {'  '.join(f'{i}={s:.3f}' for i, s in sp)}")
        print(f"    稠密   {'  '.join(f'{i}={s:.3f}' for i, s in de)}")
        print(f"    前二重合 {len(set(i for i, _ in sp) & set(i for i, _ in de))} 条")

    print()
    print("=== 稀疏与稠密的差别在哪 ===")
    print("  TF-IDF 靠字面共现：查询里的字没在文档中出现，分数就是 0")
    print("  稠密靠语义：换了说法仍能对上，但对编号、型号、精确数字不敏感")
