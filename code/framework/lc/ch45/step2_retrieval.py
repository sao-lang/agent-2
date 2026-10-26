"""第 45 章 step2：向量库 + Retriever，以及"检索进链"的三种写法（离线）。

运行：
    python code/framework/lc/ch45/step2_retrieval.py

上一级的痛点：
    第 8–11 章你手写过向量库和混合检索。真实项目里不想再造一遍，
    但也不想被某个数据库绑死。

这一级做什么：
    ① InMemoryVectorStore + 假嵌入：完整跑一遍"写入 → 相似度检索 → 过滤"
    ② 从 VectorStore 到 Retriever：接口收窄到一句话 —— retriever.invoke(query) → docs
    ③ 检索进链的三个写法：直接拼、assign 拼、create_stuff_documents_chain

看完你要能回答：
    什么时候用 VectorStore，什么时候只用 Retriever？（答案是：看你要不要写）
"""
from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.vectorstores import InMemoryVectorStore

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import EchoEmbeddings, scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


DOCS = [
    Document(page_content="退货需在签收后 30 天内申请。", metadata={"id": "p1", "topic": "退货"}),
    Document(page_content="退款将在 7 个工作日内原路退回。", metadata={"id": "p2", "topic": "退款"}),
    Document(page_content="保修期为一年，人为损坏不在保修范围。", metadata={"id": "p3", "topic": "保修"}),
    Document(page_content="运费险只在有质量问题时生效。", metadata={"id": "p4", "topic": "运费"}),
    Document(page_content="换货需要先退回原商品，再寄出新商品。", metadata={"id": "p5", "topic": "换货"}),
]


def main() -> None:
    line("① VectorStore：写入 + 相似度检索 + 元数据过滤")
    store = InMemoryVectorStore(EchoEmbeddings(size=64))
    store.add_documents(DOCS)
    print(f"  已写入 {len(DOCS)} 条")

    hits = store.similarity_search_with_score("退款 到账 工作日", k=3)
    print("  query='退款 到账 工作日'（假嵌入只认字面，注意这不是语义检索）")
    for doc, score in hits:
        print(f"    {score:.4f}  [{doc.metadata['id']}] {doc.page_content}")

    filtered = store.similarity_search("退货", k=3, filter=lambda d: d.metadata["topic"] != "退款")
    print(f"\n  加 filter（排除 topic=退款）：{[d.metadata['id'] for d in filtered]}")

    print("\n  → 真实项目把 InMemoryVectorStore 换成 Chroma / pgvector / Milvus，接口完全一样")

    line("② Retriever：接口只有一句话")
    retriever = store.as_retriever(search_kwargs={"k": 2})
    docs = retriever.invoke("保修 一年")
    print(f"  retriever.invoke('保修 一年') → {len(docs)} 条")
    for d in docs:
        print(f"    {d.metadata['id']} {d.page_content}")

    print("\n  VectorStore  vs  Retriever")
    print("    VectorStore: add / delete / search / as_retriever   （读 + 写）")
    print("    Retriever  : invoke(query) -> list[Document]         （只读，可来自任何地方）")
    print("  → 检索层只依赖 Retriever，将来换成 BM25 / API / SQL 都不用改链")

    line("③ 检索进链：最裸的写法（手拼上下文）")
    def fmt(docs_: list[Document]) -> str:
        return "\n".join(f"[{d.metadata['id']}] {d.page_content}" for d in docs_)

    rag = (
        {"context": retriever | fmt, "question": RunnablePassthrough()}
        | ChatPromptTemplate.from_template("资料：\n{context}\n\n问题：{question}")
        | scripted("退货需在 30 天内申请。[p1]")
        | StrOutputParser()
    )
    print(f"  答案 = {rag.invoke('怎么退货')!r}")
    print("  → 这个 dict 字面量会被自动转成 RunnableParallel，这是 LCEL 最常用的一招")

    line("④ 1.x 里没有 create_stuff_documents_chain —— 自己写 8 行")
    # 0.x 时代的 `langchain.chains.combine_documents` 已不在 1.x 主包里
    # （放进兼容包 langchain-classic，官方建议别新项目用）。
    # 它做的事其实只有一件：把 Document 列表拼成字符串。自己写更可控。
    prompt = ChatPromptTemplate.from_messages(
        [("system", "只根据资料回答，并标注 [id]。"), ("human", "资料：\n{context}\n\n问题：{input}")]
    )

    def stuff(docs_: list[Document]) -> str:
        return "\n".join(f"[{d.metadata['id']}] {d.page_content}" for d in docs_)

    chain = (
        {"context": lambda x: stuff(x["context"]), "input": lambda x: x["input"]}
        | prompt
        | scripted("退款 7 个工作日到账。[p2]")
        | StrOutputParser()
    )
    print(f"  答案 = {chain.invoke({'input': '退款多久', 'context': docs})!r}")
    print("  → 你在 0.x 教程里看到的 AgentExecutor / create_stuff_documents_chain，")
    print("    在 1.x 都要换成「自己组合 + create_agent」，别照抄旧代码")

    line("⑤ 检索质量才是瓶颈：同一个问题，k 从 1 到 4")
    for k in (1, 2, 4):
        got = store.as_retriever(search_kwargs={"k": k}).invoke("退款")
        print(f"  k={k} → {[d.metadata['id'] for d in got]}")
    print("  → k 越大召回越高，但上下文越长、越容易「读到无关资料」。见第 10、24 章")


if __name__ == "__main__":
    main()
