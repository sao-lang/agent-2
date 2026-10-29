"""块大小与召回：同一批问题，三种 chunk_size 的命中率，以及父子块。

用真实组件：RecursiveCharacterTextSplitter、InMemoryVectorStore、bge 嵌入、
ParentDocumentRetriever。首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

from langchain_classic.retrievers import ParentDocumentRetriever
from langchain_core.documents import Document
from langchain_core.stores import InMemoryStore
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

MODEL = "BAAI/bge-small-zh-v1.5"

DOCS = [
    Document(page_content=(
        "退货条件。质量问题导致的退货，往返运费由商家承担，买家需在签收后 7 天内提交凭证。"
        "非质量问题退货，商品需保持未拆封，运费由买家承担，申请时限同样是 7 天。"), metadata={"id": "d1"}),
    Document(page_content=(
        "生鲜类商品不支持无理由退货。若存在质量问题，请在签收后 24 小时内拍照并联系客服，"
        "逾期不再受理。生鲜订单的退款按坏果比例计算，不需要寄回。"), metadata={"id": "d2"}),
    Document(page_content=(
        "发票。发票可在订单页申请，开票时限为下单后 30 天，超过时限不再补开。"
        "电子发票在申请后 24 小时内发送到账户绑定邮箱。"), metadata={"id": "d3"}),
    Document(page_content=(
        "价保。商品签收后 15 天内出现降价，可申请补差价，每人每单限一次。"
        "活动价、优惠券抵扣后的价格不参与价保。"), metadata={"id": "d4"}),
    Document(page_content=(
        "运费门槛。单笔订单满 99 元免运费，会员每月有 3 次免运费券。"
        "偏远地区不参与包邮，具体以结算页为准。"), metadata={"id": "d5"}),
]

# (问题, 答案应包含的关键词)
QUESTIONS = [
    ("生鲜坏了要在多久内拍照", "24 小时"),
    ("发票最晚什么时候可以开", "30 天"),
    ("买完降价了能补差价吗", "15 天"),
    ("免运费要满多少钱", "99"),
    ("非质量问题退货谁出运费", "买家"),
]


def build_store(emb, chunk_size: int, overlap: int = 10):
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size,
                                              chunk_overlap=overlap)
    chunks = splitter.split_documents(DOCS)
    store = InMemoryVectorStore(embedding=emb)
    store.add_documents(chunks)
    return store, chunks


def hit_rate(store, k: int = 1) -> tuple[float, list[int]]:
    ok, lens = 0, []
    for q, expect in QUESTIONS:
        hits = store.similarity_search(q, k=k)
        lens.append(len(hits[0].page_content) if hits else 0)
        if any(expect in h.page_content for h in hits):
            ok += 1
    return ok / len(QUESTIONS), lens


def main() -> None:
    emb = HuggingFaceEmbeddings(model_name=MODEL,
                                encode_kwargs={"normalize_embeddings": True})

    print("=== 1. chunk_size 与命中率（top-1 里有没有那句话）===")
    print(f"  {'chunk_size':>10}{'块数':>6}{'平均块长':>10}{'命中率':>8}")
    for size in [40, 80, 160, 320]:
        store, chunks = build_store(emb, size)
        rate, lens = hit_rate(store)
        avg = sum(len(c.page_content) for c in chunks) / len(chunks)
        print(f"  {size:>10}{len(chunks):>6}{avg:>10.0f}{rate:>8.0%}")

    print()
    print("=== 2. 固定小块的上下文长度 ===")
    store, chunks = build_store(emb, 40)
    for q, expect in QUESTIONS[:3]:
        hit = store.similarity_search(q, k=1)[0]
        print(f"  {q:<18} 命中块 {len(hit.page_content):>3} 字：{hit.page_content[:34]!r}")

    print()
    print("=== 3. 父子块：检索用小块，交给模型用大块 ===")
    child = RecursiveCharacterTextSplitter(chunk_size=40, chunk_overlap=8)
    parent = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=20)
    vectorstore = InMemoryVectorStore(embedding=emb)
    docstore = InMemoryStore()
    retriever = ParentDocumentRetriever(
        vectorstore=vectorstore,
        docstore=docstore,
        child_splitter=child,
        parent_splitter=parent,
        search_kwargs={"k": 1},
    )
    retriever.add_documents(DOCS)
    print(f"  父块数 {len(list(docstore.yield_keys()))}，子块数 {len(vectorstore.store)}")
    for q, expect in QUESTIONS[:3]:
        got = retriever.invoke(q)
        text = got[0].page_content if got else ""
        print(f"  {q:<18} 返回 {len(text):>3} 字，含关键词 {expect in text}：{text[:36]!r}")

    print()
    print("=== 4. 同一问题，小块与父块的差别 ===")
    q = "生鲜坏了要在多久内拍照"
    small = store.similarity_search(q, k=1)[0].page_content
    big = retriever.invoke(q)[0].page_content
    print(f"  小块 {len(small):>3} 字：{small!r}")
    print(f"  父块 {len(big):>3} 字：{big[:100]!r}...")


if __name__ == "__main__":
    main()

