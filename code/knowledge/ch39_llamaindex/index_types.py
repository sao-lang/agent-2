"""第 39 章 · 三种索引与查询引擎的拆装。

运行：
    $env:PYTHONPATH="$PWD\\.libs"; $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch39_llamaindex/index_types.py

不联网。向量是哈希投影（原理演示），LLM 是固定回答的脚本：本章只看
“哪些节点被放进了提示词”，不看回答质量。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from llama_index.core import (
    Document,
    KeywordTableIndex,
    Settings,
    SimpleKeywordTableIndex,
    StorageContext,
    SummaryIndex,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, SimpleVectorStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHUNK_SIZE, ScriptedLLM, build_pipeline, make_docs, setup  # noqa: E402

QUERY = "质量问题的退货运费谁承担？"


def build_nodes():
    return build_pipeline(chunk_size=CHUNK_SIZE).run(documents=make_docs())


def coverage(prompt: str, nodes) -> int:
    """提示词里出现了几个节点的正文。"""
    return sum(node.text[:12] in prompt for node in nodes)


def section_1_three_indexes(nodes, llm: ScriptedLLM) -> None:
    print("=== 1. 三种索引：查询时拿走多少 ===")
    vs = SimpleVectorStore()
    ctx = StorageContext.from_defaults(vector_store=vs, docstore=SimpleDocumentStore())
    vindex = VectorStoreIndex(nodes, storage_context=ctx)
    print(f"  向量索引建好：向量库 {len(vs.data.embedding_dict)} 条，节点 {len(nodes)} 个")

    before = len(llm.prompts)
    vresp = vindex.as_query_engine(similarity_top_k=2).query(QUERY)
    vprompt = llm.prompts[-1]
    print(f"  VectorStoreIndex(similarity_top_k=2)：")
    print(f"    回答：{vresp.response}")
    print(f"    提示词含节点 {coverage(vprompt, nodes)}/{len(nodes)}，长度 {len(vprompt)}，LLM 调用 {len(llm.prompts) - before}")
    print(f"    source_nodes：{[(n.metadata['file'], round(n.score, 3)) for n in vresp.source_nodes]}")

    before = len(llm.prompts)
    sresp = SummaryIndex(nodes).as_query_engine().query(QUERY)
    sprompt = llm.prompts[-1]
    print(f"  SummaryIndex()：")
    print(f"    回答：{sresp.response}")
    print(f"    提示词含节点 {coverage(sprompt, nodes)}/{len(nodes)}，长度 {len(sprompt)}，LLM 调用 {len(llm.prompts) - before}")

    before = len(llm.prompts)
    kindex = KeywordTableIndex(nodes)
    kresp = kindex.as_query_engine().query(QUERY)
    kprompt = llm.prompts[-1]
    keys = list(kindex.index_struct.table)
    print(f"  KeywordTableIndex()：")
    print(f"    建索引用了 {len(llm.prompts) - before - 1} 次 LLM 抽词，关键词表 {len(keys)} 个键")
    print(f"    前两个键：{[k[:12] for k in keys[:2]]}")
    print(f"    提示词含节点 {coverage(kprompt, nodes)}/{len(nodes)}，长度 {len(kprompt)}")
    print("  关键词由脚本化 LLM 抽，所有节点抽到同一批词，检索退化成全量；")
    print("  真实模型下词会不同，但“索引质量取决于抽词那一步”不变")

    before = len(llm.prompts)
    sindex = SimpleKeywordTableIndex(nodes)
    sk = sindex.as_query_engine().query(QUERY)
    print(f"  SimpleKeywordTableIndex()（正则抽词）：source_nodes {len(sk.source_nodes)} 个")


def section_2_synthesizer(nodes, llm: ScriptedLLM) -> None:
    print("=== 2. 响应模式：一次调用还是每个节点一次 ===")
    vindex = VectorStoreIndex(nodes, vector_store=SimpleVectorStore())
    hits = vindex.as_retriever(similarity_top_k=3).retrieve(QUERY)
    print(f"  检索到 {len(hits)} 个节点：{[(h.node.ref_doc_id, round(h.score, 3)) for h in hits]}")
    for mode in ("compact", "refine", "tree_summarize"):
        before = len(llm.prompts)
        synth = get_response_synthesizer(response_mode=mode)
        resp = synth.synthesize(QUERY, nodes=hits)
        print(f"  response_mode={mode}: LLM 调用 {len(llm.prompts) - before} 次，回答长度 {len(str(resp))}")
    print("  compact 把多个块拼进一次调用；refine 逐块调用，块数决定调用数")


def section_3_filter(nodes, llm: ScriptedLLM) -> None:
    print("=== 3. 元数据过滤：先缩范围再算相似度 ===")
    vindex = VectorStoreIndex(nodes, vector_store=SimpleVectorStore())
    filters = MetadataFilters(filters=[MetadataFilter(key="file", value="invoice.md")])
    resp = vindex.as_query_engine(similarity_top_k=3, filters=filters).query("发票什么时候开？")
    print(f"  source_nodes 来自：{sorted({n.metadata['file'] for n in resp.source_nodes})}")
    print(f"  提示词里出现 policy 的内容：{any('退货' in n.text for n in resp.source_nodes)}")
    print(f"  不加过滤的 source_nodes：{[n.metadata['file'] for n in vindex.as_query_engine(similarity_top_k=3).query('发票什么时候开？').source_nodes]}")


def section_4_persist(nodes) -> None:
    print("=== 4. 索引落盘与读回 ===")
    vs = SimpleVectorStore()
    docstore = SimpleDocumentStore()
    index = VectorStoreIndex(nodes, vector_store=vs, storage_context=StorageContext.from_defaults(docstore=docstore))
    out = Path(__file__).resolve().parent / "_index_store"
    index.storage_context.persist(persist_dir=str(out))
    files = sorted(p.name for p in out.iterdir())
    print(f"  落盘文件：{files}")
    loaded = load_index_from_storage(StorageContext.from_defaults(persist_dir=str(out)))
    resp = loaded.as_query_engine(similarity_top_k=2).query(QUERY)
    print(f"  读回后查询：回答={resp.response!r}，source_nodes={len(resp.source_nodes)} 个")
    print(f"  读回后向量库条数：{len(loaded.vector_store.data.embedding_dict)}")
    shutil.rmtree(out)


def main() -> None:
    llm = setup()
    nodes = build_nodes()
    print(f"语料：{len(nodes)} 个节点，{sorted({n.metadata['file'] for n in nodes})}")
    section_1_three_indexes(nodes, llm)
    section_2_synthesizer(nodes, llm)
    section_3_filter(nodes, llm)
    section_4_persist(nodes)


if __name__ == "__main__":
    main()
