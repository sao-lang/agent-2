"""用 LangChain 的真实组件搭一条 RAG 链，并对引用做校验。

组件都是真的：Document、RecursiveCharacterTextSplitter、InMemoryVectorStore、
bge 嵌入、Retriever、create_retrieval_chain。只有模型是脚本化的
（FakeListChatModel），用来演示装配与校验；换成真实模型改构造那一行即可。

首次运行需下载 bge-small-zh-v1.5（约 95 MB）：
    $env:HF_ENDPOINT = "https://hf-mirror.com"
    $env:HF_HUB_DISABLE_SYMLINKS = "1"
"""

from __future__ import annotations

import re

from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

MODEL = "BAAI/bge-small-zh-v1.5"

RAW = [
    {"id": "d1", "source": "policy/return.md",
     "text": "退货运费按责任划分。质量问题导致的退货，往返运费由商家承担，"
             "用户无需支付。非质量问题（不喜欢、买错型号）的退货，运费由买家承担。"
             "运费由谁承担的判定依据是售后审核结论，不是用户自述。"},
    {"id": "d2", "source": "policy/return.md",
     "text": "签收后 7 天内可申请无理由退货，商品需保持未拆封状态，配件与赠品需一并寄回。"
             "超过 7 天的申请，只能在质量问题通道处理。"},
    {"id": "d3", "source": "policy/invoice.md",
     "text": "发票可在订单页申请。开票时限为下单后 30 天，超过时限只能开具消费凭证。"
             "电子发票在申请后 24 小时内发送到账户绑定邮箱，纸质发票随退货流程单独处理。"},
    {"id": "d4", "source": "policy/fresh.md",
     "text": "生鲜类商品不支持无理由退货，因为无法二次销售。质量问题请在签收后 24 小时内"
             "拍照反馈，客服核对后按坏果比例退款，不需要寄回。"},
]

CITE = re.compile(r"\[(d\d+)\]")

PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "只依据给定的参考资料回答，资料不足时回答：资料里没有相关内容。"
     "每个结论后面用 [编号] 标注来源，编号取参考资料每行开头的 id。"),
    ("human", "参考资料：\n{context}\n\n问题：{input}"),
])


def build():
    docs = [Document(page_content=d["text"],
                     metadata={"id": d["id"], "source": d["source"]})
            for d in RAW]
    splitter = RecursiveCharacterTextSplitter(chunk_size=45, chunk_overlap=8)
    chunks = splitter.split_documents(docs)
    for i, c in enumerate(chunks):
        c.metadata["chunk"] = i
    emb = HuggingFaceEmbeddings(model_name=MODEL,
                                encode_kwargs={"normalize_embeddings": True})
    store = InMemoryVectorStore(embedding=emb)
    store.add_documents(chunks)
    return store, chunks, emb


def citation_report(answer: str, context: list[Document]) -> dict:
    """引用率看有没有标，引用正确率看标得对不对。"""
    ids = {d.metadata["id"] for d in context}
    cited = CITE.findall(answer)
    return {
        "cited": cited,
        "has_citation": bool(cited),
        "all_valid": bool(cited) and all(c in ids for c in cited),
        "available": sorted(ids),
    }


def run(question: str, scripted_answer: str, retriever):
    llm = FakeListChatModel(responses=[scripted_answer])
    chain = create_retrieval_chain(
        retriever, create_stuff_documents_chain(llm, PROMPT))
    return chain.invoke({"input": question})


if __name__ == "__main__":
    store, chunks, emb = build()

    print("=== 1. 建库：文档 → 切块 → 向量 ===")
    print(f"  原始文档 {len(RAW)} 条，切块后 {len(chunks)} 块，维度 {len(emb.embed_query('x'))}")
    for c in chunks[:5]:
        print(f"  [{c.metadata['id']}#{c.metadata['chunk']}] {c.page_content[:34]}")
    print(f"  ... 共 {len(chunks)} 块")

    print()
    print("=== 2. 检索：三个查询的召回与分数 ===")
    for q in ["质量问题退货运费谁出", "发票多久能开", "耳机保修几年"]:
        hits = store.similarity_search_with_score(q, k=3)
        row = "  ".join(f"{d.metadata['id']}={s:.3f}" for d, s in hits)
        print(f"  {q:<16} {row}")

    retriever = store.as_retriever(search_kwargs={"k": 3})
    cases = [
        ("质量问题退货运费谁出", "质量问题由商家承担运费 [d1]。", "正常"),
        ("质量问题退货运费谁出", "退货一律由买家承担运费 [d9]。", "编造引用"),
        ("质量问题退货运费谁出", "运费由商家承担。", "无引用"),
        ("耳机保修几年", "资料里没有相关内容。", "拒答"),
    ]

    print()
    print("=== 3. 四次调用：返回结构与引用校验 ===")
    for q, answer, label in cases:
        out = run(q, answer, retriever)
        rep = citation_report(out["answer"], out["context"])
        print(f"\n  [{label}] 输入 {out['input']!r}")
        print(f"    召回 {[d.metadata['id'] for d in out['context']]}  "
              f"可用 {rep['available']}")
        print(f"    回答 {out['answer']!r}")
        print(f"    引用 {rep['cited']}  有引用={rep['has_citation']}  "
              f"全部有效={rep['all_valid']}")

    print()
    print("=== 4. 两个比率（拒答不计入引用率的分母）===")
    answered = [c for c in cases if c[2] != "拒答"]
    reports = [(citation_report(o["answer"], o["context"]), o["answer"])
               for o in (run(q, a, retriever) for q, a, _ in answered)]
    rate = sum(1 for r, _ in reports if r["has_citation"]) / len(reports)
    valid = sum(1 for r, _ in reports if r["all_valid"]) / len(reports)
    print(f"  引用率 {rate:.0%}  引用正确率 {valid:.0%}  "
          f"（分母 {len(reports)} 条，不含拒答）")
    print("  两个率一起看：引用率高而正确率低，说明模型在乱标来源")
