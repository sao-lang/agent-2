"""第 51 章 step3：路由、多跳（SubQuestion）、持久化，以及与 LangChain 的取舍（离线）。

运行：
    python code/framework/li/ch51/step3_advanced.py

上一级的痛点：
    一个索引只能回答"这一批文档里有什么"。真实项目有多个知识库（政策 / 产品 / 工单），
    还有"要串两个库才能答"的问题，以及"重启后索引要还在"。

这一级做什么：
    ① RouterQueryEngine：按问题类型选不同的"引擎"
    ② SubQuestionQueryEngine：把多跳问题拆成子问题，分别查再合并
    ③ persist / load：索引落盘，重启不用重建
    ④ LangChain vs LlamaIndex 的取舍（一段话 + 一张表）
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM
from llama_index.core.query_engine import RouterQueryEngine, SubQuestionQueryEngine
from llama_index.core.selectors import LLMSingleSelector
from llama_index.core.tools import QueryEngineTool, ToolMetadata

POLICY = """退货需在签收后 30 天内申请。
退款将在 7 个工作日内原路退回。
保修期为一年，人为损坏不在保修范围。"""

PRODUCT = """AirPods Pro 2 支持主动降噪，单次续航 6 小时。
保修期一年，电池容量低于 80% 可申请检测。
充电盒支持 MagSafe 无线充电。"""


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def make_index(text: str) -> VectorStoreIndex:
    return VectorStoreIndex([Document(text=text)], embed_model=MockEmbedding(embed_dim=8))


def main() -> None:
    Settings.llm = MockLLM(max_tokens=64)
    Settings.embed_model = MockEmbedding(embed_dim=8)

    line("① RouterQueryEngine：按问题选知识库")
    policy_idx = make_index(POLICY)
    product_idx = make_index(PRODUCT)

    tools = [
        QueryEngineTool(
            query_engine=policy_idx.as_query_engine(),
            metadata=ToolMetadata(
                name="policy",
                description="售后政策：退货期限、退款时效、保修范围。问政策时用。",
            ),
        ),
        QueryEngineTool(
            query_engine=product_idx.as_query_engine(),
            metadata=ToolMetadata(
                name="product",
                description="产品参数：续航、降噪、充电方式。问产品功能时用。",
            ),
        ),
    ]
    router = RouterQueryEngine(selector=LLMSingleSelector.from_defaults(), query_engine_tools=tools)
    print(f"  路由引擎 = {type(router).__name__}，候选工具 = {[t.metadata.name for t in tools]}")
    print("  → 它做的事和 create_agent(tools=[...]) 很像，区别是：")
    print("    Router 只选**一次**，不做多轮循环；Agent 可以连续调多个工具。")

    line("② SubQuestionQueryEngine：把多跳问题拆开")
    from llama_index.core import get_response_synthesizer
    from llama_index.core.question_gen import LLMQuestionGenerator

    sub = SubQuestionQueryEngine(
        question_gen=LLMQuestionGenerator.from_defaults(),
        response_synthesizer=get_response_synthesizer(),
        query_engine_tools=tools,
        verbose=False,
    )
    print(f"  多跳引擎 = {type(sub).__name__}")
    print("  ⚠️ 注意：`SubQuestionQueryEngine.from_defaults()` 会尝试 import")
    print("     `llama-index-question-gen-openai`（一个可选包）。离线环境必须像上面这样")
    print("     手动传 question_gen + response_synthesizer —— 这是本仓库踩过的坑。")
    print("""  它内部做四步：
    1. 让模型把问题拆成子问题（"退款时效？" + "AirPods 保修多久？"）
    2. 每个子问题路由到对应知识库
    3. 分别检索 + 合成
    4. 把子答案合成总答案

  → 这是"多跳"的**查询侧**解法，和第 29 章的"图游走"是两条路：
      查询侧：拆问题（无需建图，成本 1+N 次调用）
      索引侧：建图（建库贵，查询便宜）
  → 判据：问题能拆成清晰的子问题 → 查询侧；子问题之间互相依赖 → 索引侧。""")

    line("③ persist / load：索引落盘")
    persist_dir = Path(tempfile.mkdtemp()) / "idx"
    idx = make_index(POLICY)
    idx.storage_context.persist(persist_dir=str(persist_dir))
    files = sorted(p.name for p in persist_dir.iterdir())
    print(f"  落盘目录 {persist_dir.name}/ 里有：{files}")
    print("  → docstore.json（原文）/ index_store.json（结构）/ default__vector_store.json（向量）")
    print("     另两个（graph_store / image__vector_store）是空壳，共 5 个文件")

    # 重新加载（模拟进程重启）
    Settings.embed_model = MockEmbedding(embed_dim=8)
    ctx = StorageContext.from_defaults(persist_dir=str(persist_dir))
    loaded = load_index_from_storage(ctx)
    r = loaded.as_retriever(similarity_top_k=1).retrieve("退款多久")
    print(f"  重载后检索 → {len(r)} 条：{r[0].node.get_content()[:32]!r}")

    line("④ 生产上怎么做持久化")
    print("""  本地小规模：StorageContext.persist()（本章）
  生产：
    · docstore → Redis / Postgres（存原文与元数据）
    · vector_store → Qdrant / pgvector / Milvus（存向量）
    · index_store → Redis（存索引结构）
    · 三者通过 StorageContext.from_defaults(docstore=..., vector_store=..., index_store=...) 组合
  → 这样"重建索引"和"换向量库"可以分开做。""")

    line("⑤ LangChain vs LlamaIndex：到底用哪个")
    print("""  LangChain / LangGraph 强在：
    · 编排（LCEL、中间件、图、状态、HITL、流式）
    · 工具/Agent 生态
    · 一个"通用的胶水层"

  LlamaIndex 强在：
    · 文档接入（各种 Reader：PDF / docx / 网页 / 数据库）
    · Node 体系（id / metadata / 前后关系 / 父子关系）
    · 检索后处理（PostProcessor 链）
    · 查询引擎（Router / SubQuestion / Recursive）
    · 索引持久化的默认方案更完整

  取舍建议：
    · 项目主体是"多源文档 → 可查询知识库" → 以 LlamaIndex 为主
    · 项目主体是"Agent 做多步任务" → 以 LangGraph 为主
    · 两者可以混：LlamaIndex 管索引，把 QueryEngine 包成 LangChain Tool 交给 Agent
  """)

    line("⑥ 混用的具体形状（三行伪代码）")
    print("""  from langchain_core.tools import StructuredTool

  tool = StructuredTool.from_function(
      func=lambda q: str(index.as_query_engine().query(q)),
      name="kb_search",
      description="在企业知识库里检索并回答。涉及政策、参数时用。",
  )
  agent = create_agent(model, tools=[tool])   # ← 第 46 章的 Agent
  """)


if __name__ == "__main__":
    main()
