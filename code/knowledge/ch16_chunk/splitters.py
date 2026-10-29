"""五种切法在同一份文档上的结果对比。

全部用真实组件：CharacterTextSplitter、RecursiveCharacterTextSplitter、
MarkdownHeaderTextSplitter、from_tiktoken_encoder、SemanticChunker。
SemanticChunker 需要嵌入模型，首次运行要下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import (
    CharacterTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

DOC = """# 售后政策

## 退货条件

质量问题退货，运费由商家承担，买家需在签收后 7 天内提交凭证。
非质量问题退货，商品需保持未拆封，运费由买家承担，申请时限同样是 7 天。

## 生鲜类

生鲜类商品不支持无理由退货。若存在质量问题，请在签收后 24 小时内
拍照并联系客服，逾期不再受理。

## 发票

发票可在订单页申请，开票时限为下单后 30 天，超过时限不再补开。

## 运费对照表

| 场景 | 谁承担 | 时限 |
|---|---|---|
| 质量问题 | 商家 | 7 天 |
| 非质量问题 | 买家 | 7 天 |
| 生鲜质量问题 | 商家 | 24 小时 |
"""


def show(title: str, chunks: list, limit: int = 4) -> None:
    print(f"\n  [{title}] {len(chunks)} 块，长度 {[len(c.page_content) if hasattr(c, 'page_content') else len(c) for c in chunks]}")
    for c in chunks[:limit]:
        text = c.page_content if hasattr(c, "page_content") else c
        meta = getattr(c, "metadata", {})
        tag = f" {meta}" if meta else ""
        print(f"    {text[:38]!r}{'...' if len(text) > 38 else ''}{tag}")


def main() -> None:
    print("=== 五种切法，同一份文档 ===")

    show("CharacterTextSplitter（按段落分隔）",
         CharacterTextSplitter(separator="\n\n", chunk_size=80, chunk_overlap=0)
         .split_text(DOC))

    show("RecursiveCharacterTextSplitter（递归分隔符）",
         RecursiveCharacterTextSplitter(chunk_size=80, chunk_overlap=20)
         .split_text(DOC))

    md = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"), ("##", "h2")])
    show("MarkdownHeaderTextSplitter（按标题）", md.split_text(DOC))

    tok = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base", chunk_size=60, chunk_overlap=10)
    show("from_tiktoken_encoder（按 token 数）", tok.split_text(DOC))

    emb = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5",
                                encode_kwargs={"normalize_embeddings": True})
    sem = SemanticChunker(emb, breakpoint_threshold_type="percentile",
                          breakpoint_threshold_amount=80)
    show("SemanticChunker（默认英文断句）", sem.split_text(DOC))

    sem_zh = SemanticChunker(emb, breakpoint_threshold_type="percentile",
                             breakpoint_threshold_amount=80,
                             sentence_split_regex=r"(?<=[。！？；\n])")
    show("SemanticChunker（中文断句正则）", sem_zh.split_text(DOC))

    print()
    print("=== 表格被切断的样子 ===")
    table = [c for c in RecursiveCharacterTextSplitter(
        chunk_size=40, chunk_overlap=0).split_text(DOC) if "|" in c]
    for c in table:
        print(f"    {c!r}")

    print()
    print("=== 标题信息在切块后还在不在 ===")
    for src, chunks in [("Recursive", RecursiveCharacterTextSplitter(
            chunk_size=80, chunk_overlap=20).split_text(DOC)),
            ("Markdown", md.split_text(DOC))]:
        first = chunks[1]
        meta = getattr(first, "metadata", {})
        print(f"  {src:<10} 第二块 metadata={meta}  正文前 20 字={str(getattr(first, 'page_content', first))[:20]!r}")


if __name__ == "__main__":
    main()

