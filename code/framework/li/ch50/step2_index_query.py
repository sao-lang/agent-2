"""第 50 章 step2：Index / Retriever / QueryEngine 三层（离线）。

运行：
    python code/framework/li/ch50/step2_index_query.py

上一级的痛点：
    你有了一堆 Node，但"怎么检索、怎么拼上下文、怎么调模型"还没解决。

这一级做什么：
    ① VectorStoreIndex：从 nodes 建索引（真的是"建"，不是"包一层"）
    ② as_retriever：只拿"检索"这一层（和第 44 章 LangChain 的 Retriever 对齐）
    ③ as_query_engine：检索 + 合成（这一步 LlamaIndex 帮你拼 prompt）
    ④ PostProcessor：检索后再过滤/压缩（这是 LlamaIndex 的强项）
    ⑤ node_postprocessors 的顺序很关键（先用 top_k 再用阈值，和反过来，结果不同）

关键认知：
    **Index 是"存储 + 索引结构"，Retriever 是"取"，QueryEngine 是"取 + 合成"。**
    三者分开才能替换其中任意一层。
"""
from __future__ import annotations

from pathlib import Path

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

DOC_PATH = Path(__file__).resolve().parents[4] / "data" / "售后政策手册.md"


class CharHashEmbedding(MockEmbedding):
    """确定性字符哈希向量。

    为什么不用 MockEmbedding？因为它对**任何**文本都返回同一个向量
    （实例里是 [0.5] * dim）—— 那所有块的相似度都是 1.0，检索结果毫无意义。
    为了能演示"阈值过滤"到底在过滤什么，这里用真实一点的确定性向量。
    """

    def __init__(self, dim: int = 64) -> None:
        super().__init__(embed_dim=dim)

    def _vec(self, text: str) -> list[float]:
        import hashlib
        import math

        v = [0.0] * self.embed_dim
        for ch in text:
            h = int(hashlib.md5(ch.encode()).hexdigest()[:8], 16)
            v[h % self.embed_dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vec(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vec(query)


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def build_index() -> VectorStoreIndex:
    text = DOC_PATH.read_text(encoding="utf-8")
    splitter = SentenceSplitter(chunk_size=160, chunk_overlap=20,
                                secondary_chunking_regex="[^，。；！？]+[，。；！？]?")
    doc = Document(text=text, metadata={"source": "售后政策手册.md", "topic": "售后"})
    nodes = splitter.get_nodes_from_documents([doc])
    return VectorStoreIndex(nodes, embed_model=CharHashEmbedding(dim=64))


def show(title: str, nodes: list[NodeWithScore], k: int = 3) -> None:
    print(f"  {title}")
    for n in nodes[:k]:
        c = n.node.get_content().replace("\n", " ")
        print(f"    {n.score if n.score is not None else 0:.3f}  {c[:52]}…")


def main() -> None:
    line("① VectorStoreIndex：从节点建索引")
    index = build_index()
    print(f"  索引类型 = {type(index).__name__}")
    ds = index.docstore
    print(f"  docstore 里的节点数 = {len(ds.docs)}")
    print("  → 索引内部持有：docstore（原文）+ index_store（结构）+ vector_store（向量）")
    print("    三者在 StorageContext 里，可以分别换成 Postgres / Qdrant / Redis（见 50.10）")

    q = "退款多久到账？"

    line("② as_retriever：只拿检索这一层")
    retriever = index.as_retriever(similarity_top_k=3)
    got = retriever.retrieve(q)
    show(f"retrieve({q!r}) → {len(got)} 条：", got)

    line("③ as_query_engine：检索 + 合成（它会自己拼 prompt）")
    from llama_index.core import Settings
    from llama_index.core.llms import MockLLM

    Settings.llm = MockLLM(max_tokens=32)     # 离线：不真的生成，只验证链路
    qe = index.as_query_engine(similarity_top_k=3)
    resp = qe.query(q)
    print(f"  query_engine 返回类型 = {type(resp).__name__}")
    print(f"  回答（MockLLM 只会重复 'text'）= {resp.response[:40]!r}")
    print(f"  引用节点数 = {len(resp.source_nodes)}")
    print("  → 关键：`resp.source_nodes` 就是**这次回答用到的块**。")
    print("    第 40 章做 RAG 评测时，'引用是否正确'就靠它，而不是靠模型自己说'根据第几节'。")
    print("  → query_engine 的内部顺序：retriever → node_postprocessors → response_synthesizer")
    print("    把'检索'和'生成'混在一起，答错了你分不清是哪段的锅 —— 所以评测要分开测。")

    line("④ PostProcessor：检索后过滤（LlamaIndex 的强项）")
    print("  不给 threshold 时，top_k=6 的结果：")
    raw = index.as_retriever(similarity_top_k=6).retrieve(q)
    for n in raw:
        print(f"    {n.score:.3f}  {n.node.get_content().replace(chr(10), ' ')[:48]}…")

    pp = SimilarityPostprocessor(similarity_cutoff=0.33)
    filtered = pp.postprocess_nodes(raw, query_str=q)
    print(f"\n  加 SimilarityPostprocessor(cutoff=0.33) 后：{len(filtered)} 条")
    for n in filtered:
        print(f"    {n.score:.3f}  {n.node.get_content().replace(chr(10), ' ')[:48]}…")
    print("  → 作用：把'分数很低但也进了 top_k'的块剔掉，避免噪声进 prompt。")
    print("    这是第 10 章'重排之后还要过滤'的框架化写法。")

    line("⑤ 顺序很重要：先 top_k 再阈值 vs 反过来")
    print("  顺序 A：先取 top_6 → 再按 0.33 过滤 →", len(filtered), "条")
    small = index.as_retriever(similarity_top_k=2).retrieve(q)
    filtered_small = SimilarityPostprocessor(similarity_cutoff=0.33).postprocess_nodes(small, query_str=q)
    print("  顺序 B：先取 top_2 → 再按 0.33 过滤 →", len(filtered_small), "条")
    print(f"  → A 从 6 条里筛出 {len(filtered)} 条（可保留 ≤6 条），B 最多只能有 2 条。")
    print("    先收窄再过滤 = 把'可能被过滤掉、但其实是好块'的候选提前扔了。")

    line("⑥ 元数据过滤：只在这个主题里检索")
    flt = MetadataFilters(filters=[MetadataFilter(key="source", value="售后政策手册.md")])
    fr = index.as_retriever(similarity_top_k=3, filters=flt).retrieve(q)
    print(f"  带 source 过滤 → {len(fr)} 条（多租户/多知识库场景必备）")
    print("  → 第 40 章讲过：**过滤比'让向量去区分'可靠得多**。")

    line("⑦ 三种 Index 的区别（你只需要记住 VectorStoreIndex）")
    print("""  VectorStoreIndex   向量索引（最常用，本章用这个）
  SummaryIndex       全文顺序遍历（适合"总结整篇"，不适合 QA）
  KeywordTableIndex  关键词表（简单但脆，现在很少用）
  PropertyGraphIndex 图索引（对应第 28 章 GraphRAG）

  → 90% 的 RAG 项目用 VectorStoreIndex + 好的切分 + 好的 rerank 就够了。
  """)


if __name__ == "__main__":
    main()
