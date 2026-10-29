"""重排、MMR、多查询改写：三种"在检索之后再做一层"的手段。

用真实组件：CrossEncoderReranker（bge-reranker-base）、ContextualCompressionRetriever、
MMR 检索、MultiQueryRetriever（脚本化 LLM）。
首次运行需下载 bge-small（约 95 MB）与 bge-reranker-base（约 1.1 GB）。
"""

from __future__ import annotations

from langchain_classic.retrievers import ContextualCompressionRetriever, MultiQueryRetriever
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.cross_encoders import HuggingFaceCrossEncoder

from retrieval_quality import DOCS, QUERIES, evaluate, recall_at

EMB_MODEL = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"


def main() -> None:
    docs = [Document(page_content=text, metadata={"id": i}) for i, text in DOCS]
    emb = HuggingFaceEmbeddings(model_name=EMB_MODEL,
                                encode_kwargs={"normalize_embeddings": True})
    store = InMemoryVectorStore(embedding=emb)
    store.add_documents(docs)

    base = store.as_retriever(search_kwargs={"k": 5})
    wide = store.as_retriever(search_kwargs={"k": 10})

    base_res = [[d.metadata["id"] for d in base.invoke(q)] for q, _ in QUERIES]
    print("=== 1. 基线：稠密 top-5 ===")
    evaluate("稠密 top-5", base_res)

    print()
    print("=== 2. 重排：先取 10 条，再用 cross-encoder 排前 5 ===")
    reranker = CrossEncoderReranker(
        model=HuggingFaceCrossEncoder(model_name=RERANK_MODEL), top_n=5)
    rerank = ContextualCompressionRetriever(base_compressor=reranker, base_retriever=wide)
    rerank_res = [[d.metadata["id"] for d in rerank.invoke(q)] for q, _ in QUERIES]
    evaluate("稠密 + 重排", rerank_res)

    print()
    print("=== 3. 重排前后，第一条正确结果的位置 ===")
    rows = []
    for q, rel in QUERIES:
        before = [d.metadata["id"] for d in wide.invoke(q)]
        after = [d.metadata["id"] for d in rerank.invoke(q)]

        def first_rank(ids):
            for i, doc_id in enumerate(ids, 1):
                if doc_id in rel:
                    return i
            return 99

        rows.append((q, first_rank(before), first_rank(after)))
    for q, b, a in rows:
        mark = "  <- 改善" if a < b else ""
        print(f"  {q:<16} 重排前 {b:>2} -> 重排后 {a:>2}{mark}")
    better = sum(1 for _, b, a in rows if a < b)
    worse = sum(1 for _, b, a in rows if a > b)
    print(f"  改善 {better} 条，变差 {worse} 条，不变 {len(rows) - better - worse} 条")

    print()
    print("=== 4. MMR：λ 不同，前 5 条的多样性不同 ===")
    q, rel = "退货需要拆封吗", {"d3", "d16"}
    for lam in [1.0, 0.7, 0.3]:
        mmr = store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 5, "fetch_k": 10, "lambda_mult": lam},
        )
        ids = [d.metadata["id"] for d in mmr.invoke(q)]
        print(f"  λ={lam:<4} 前 5 条 {ids}  recall@5 {recall_at(ids, rel, 5):.2f}")

    print()
    print("=== 5. 多查询：三条改写各查一次，取并集 ===")
    llm = FakeListChatModel(responses=[
        "生鲜坏了怎么申请退款\n生鲜质量问题多久内反馈\n生鲜商品退货政策"
    ])
    multi = MultiQueryRetriever.from_llm(retriever=base, llm=llm,
                                         include_original=True)
    q, rel = QUERIES[0]
    single = [d.metadata["id"] for d in base.invoke(q)]
    merged = [d.metadata["id"] for d in multi.invoke(q)]
    print(f"  原查询 {q!r} 单次召回 {single}")
    print(f"  多查询并集        {merged}")
    print(f"  recall@5 单次 {recall_at(single, rel, 5):.2f} -> "
          f"多查询 {recall_at(merged, rel, 5):.2f}")


if __name__ == "__main__":
    main()

