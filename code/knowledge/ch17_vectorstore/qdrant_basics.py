"""向量库三件事：索引取舍、过滤位置、距离度量。

用真实组件：QdrantClient（本地内存模式）、QdrantVectorStore、bge 嵌入。
首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

import time

import numpy as np
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    VectorParams,
)

MODEL = "BAAI/bge-small-zh-v1.5"
N_DOCS = 1200

TOPICS = [
    "退货条件与运费承担，质量问题由商家承担往返运费，非质量问题由买家承担。",
    "生鲜类商品不支持无理由退货，质量问题需在签收后 24 小时内拍照反馈。",
    "发票可在订单页申请，开票时限为下单后 30 天，电子发票 24 小时内送达。",
    "价保规则：签收后 15 天内降价可补差价，活动价与优惠券不参与。",
    "运费门槛：单笔满 99 元免运费，偏远地区不参与包邮。",
    "换货流程：收到商品 7 天内可申请换货，需保持未拆封并附赠品。",
    "退款到账：原路退回，银行卡 3 到 7 个工作日，余额实时到账。",
    "会员权益：每月 3 次免运费券，生日月双倍积分。",
]

QUERIES = [
    "生鲜坏了多久内要拍照",
    "发票最晚什么时候开",
    "买完降价能补差价吗",
    "免运费门槛是多少",
    "退款多久到账",
]


def make_corpus() -> tuple[list[Document], list[str]]:
    docs, ids = [], []
    for i in range(N_DOCS):
        topic = TOPICS[i % len(TOPICS)]
        tenant = "t_a" if i % 4 else "t_b"
        text = f"{topic}（第 {i} 条记录，租户 {tenant}）"
        docs.append(Document(
            page_content=text,
            metadata={"tenant": tenant, "topic": i % len(TOPICS), "_id": i},
        ))
        ids.append(i)
    return docs, ids


def new_store(client, name, dim, emb, dist=Distance.COSINE, hnsw=None) -> QdrantVectorStore:
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dim, distance=dist),
        hnsw_config=hnsw,
    )
    return QdrantVectorStore(client=client, collection_name=name,
                             embedding=emb, distance=dist)


def main() -> None:
    emb = HuggingFaceEmbeddings(model_name=MODEL,
                                encode_kwargs={"normalize_embeddings": True})
    docs, ids = make_corpus()

    t0 = time.perf_counter()
    vectors = emb.embed_documents([d.page_content for d in docs])
    print(f"嵌入 {len(vectors)} 条，耗时 {time.perf_counter() - t0:.1f}s，"
          f"维度 {len(vectors[0])}")
    mat = np.array(vectors, dtype=np.float32)

    qvecs = [emb.embed_query(q) for q in QUERIES]
    truth = [set(np.argsort(-(mat @ np.array(qv)))[:10].tolist()) for qv in qvecs]

    client = QdrantClient(":memory:")
    base = new_store(client, "base", len(vectors[0]), emb)
    base.add_documents(docs, ids=ids)
    print(f"  写入 {client.count('base').count} 条")

    print()
    print("=== 1. HNSW 参数与召回（recall@10，以暴力检索为真值）===")
    for name, hnsw in [("m=16（默认）", None), ("m=2, ef_construct=4", HnswConfigDiff(m=2, ef_construct=4))]:
        coll = "c_" + name.split("=")[1].split(",")[0].strip()
        store = new_store(client, coll, len(vectors[0]), emb, hnsw=hnsw)
        store.add_documents(docs, ids=ids)
        recs, times = [], []
        for qv, tv in zip(qvecs, truth):
            t = time.perf_counter()
            got = store.similarity_search_by_vector(qv, k=10)
            times.append((time.perf_counter() - t) * 1000)
            got_ids = {int(d.metadata["_id"]) for d in got}
            recs.append(len(got_ids & tv) / 10)
        print(f"  {name:<20} recall@10 {sum(recs) / len(recs):.2f}  "
              f"单次查询 {sum(times) / len(times):.1f} ms")

    t = time.perf_counter()
    for qv in qvecs:
        np.argsort(-(mat @ np.array(qv)))[:10]
    brute_ms = (time.perf_counter() - t) * 1000 / len(qvecs)
    label = "暴力全扫（numpy）"
    print(f"  {label:<20} recall@10 1.00  单次查询 {brute_ms:.2f} ms")

    print()
    print("=== 2. 过滤发生在检索前还是检索后 ===")
    flt = Filter(must=[FieldCondition(key="metadata.tenant", match=MatchValue(value="t_b"))])
    n_b = sum(1 for d in docs if d.metadata["tenant"] == "t_b")
    print(f"  租户 t_b 的块数 {n_b} / {N_DOCS}（占 {n_b / N_DOCS:.0%}）")
    for q in QUERIES[:3]:
        pre = base.similarity_search(q, k=10, filter=flt)
        post = base.similarity_search(q, k=10)
        post_b = [d for d in post if d.metadata["tenant"] == "t_b"]
        print(f"  {q:<16} 预过滤取回 {len(pre):>2} 条 / 后过滤只剩 {len(post_b)} 条")

    print()
    print("=== 3. 三种距离在同一批向量上的读数 ===")
    for dist in [Distance.COSINE, Distance.DOT, Distance.EUCLID]:
        coll = f"dist_{dist.value.lower()}"
        store = new_store(client, coll, len(vectors[0]), emb, dist=dist)
        store.add_documents(docs, ids=ids)
        scored = store.similarity_search_with_score(QUERIES[0], k=3)
        row = "  ".join(f"{sc:.3f}" for _, sc in scored)
        print(f"  {dist.value:<8} 前三条分数 {row}")

    print()
    print("=== 4. 写入幂等与按条件删除 ===")
    before = client.count("base").count
    base.add_documents(docs[:10], ids=ids[:10])
    after = client.count("base").count
    print(f"  同 id 重写 10 条：{before} -> {after}")
    client.delete(collection_name="base", points_selector=flt)
    left = client.count("base").count
    print(f"  按租户 t_b 删除后：{after} -> {left}（删掉 {after - left} 条）")


if __name__ == "__main__":
    main()




