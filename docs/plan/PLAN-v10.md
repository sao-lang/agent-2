> **本文件已被 [PLAN-v11.md](./PLAN-v11.md) 取代。** v11 明确 RAG 章以 RAG 为主、LangChain 为副线（约 70/30），副线负责全部代码示例并附 API 覆盖清单。

# 改造方案 v10：LangChain 前置（agent 侧）＋ RAG 只讲 RAG 相关

> 取代 v7/v8/v9。本版按最新要求：
> 1. **LangChain 与 agent 相关的内容先讲完**（第 9–12 章），作为进入 RAG 的平滑过渡。
> 2. **RAG 卷只讲 LangChain 中与 RAG 相关的内容**（嵌入、切块、向量库、检索、装配、记忆、治理），代码全部用 LangChain。
> 3. 基础概念仍然先讲，代码紧跟其后。
> 4. 进阶（范式/反思/状态/持久化）与工程化在 RAG 之后；多智能体、LangGraph 更后。
> 5. 框架能力不压缩：LangChain 共 4 章（agent 侧）+ 8 章 RAG 侧的落地。

---

## 一、总原则

| # | 原则 | 做法 |
|---|---|---|
| 1 | 概念先讲 | 每章先"是什么 / 不做会怎么坏"，再给代码 |
| 2 | 框架分段 | LangChain 的 agent 侧（9–12）在 RAG 之前；RAG 侧（13–21）在 RAG 卷内 |
| 3 | 代码统一 | 第 9–12 章与第 13–21 章全部用 LangChain；RAG 卷不再手写向量/检索 |
| 4 | 平滑过渡 | 第 12 章末尾用一节讲"agent 需要外部知识时缺什么"，第 13 章从这个问题接上 |
| 5 | 进阶后置 | 范式/反思/状态/持久化/MCP·Skill 在 RAG 之后 |
| 6 | 其他框架靠后 | LangGraph（36–38）、LlamaIndex（39–40）、其他栈（41）在最后统一讲 |

---

## 二、全书结构（52 章，0–51）

| 卷 | 名称 | 章 | 说明 |
|---|---|---|---|
| 0 | 起点 | 0 | agent 是什么 |
| 1 | 一次调用 | 1–5 | 四字段 / 编与忘 / token 成本 / 结构化输出 / **pydantic** |
| 2 | 最小 agent | 6–8 | 工具 / 循环 / 终止与失控 |
| 3 | **LangChain（agent 侧）** | 9–12 | 基础 / 组合 / 工具 / Agent，末尾过渡到 RAG |
| 4 | **RAG（LangChain 侧）** | 13–21 | 分流 / 四环节 / 向量化 / 切块 / 向量库 / 检索质量 / 装配 / 记忆 / 治理 |
| 5 | agent 进阶 | 22–26 | 范式 / 反思 / 状态 / 持久化 / MCP·Skill |
| 6 | agent 工程化 | 27–32 | 沙箱 / 护栏 / 注入 / 审批 / 对外形态 / 交付 |
| 7 | 多智能体 | 33–35 | 拆分与协作 / A2A / 手写编排 |
| 8 | LangGraph | 36–38 | 图与状态 / 持久化与流式 / 多智能体编排 |
| 9 | 其他框架 | 39–41 | LlamaIndex 两章 / 其他技术栈与平台 |
| 10 | 度量与复盘 | 42–46 | 计量（OTel+LangFuse）/ RAG 评测（RAGAS）/ Agent 评测 / 门禁 / 成本延迟 |
| 11 | 组件封装（副线） | 47–51 | 契约与替换实验 |

知识点：A9 + B21 + **C14** + **D16** + E14 + F18 + **H14** + G5 = **111 条**。

---

## 三、LangChain（agent 侧）四章逐节

**第 9 章 · LangChain 基础：包、模型、消息**

| 节 | 内容 |
|---|---|
| 9.1 | 包结构：`langchain-core`/`langchain`/`langchain-openai`/`langchain-community`；版本边界 |
| 9.2 | `init_chat_model` 参数矩阵；OpenAI 兼容端点（`base_url`） |
| 9.3 | 四种消息与 `content` vs `content_blocks` |
| 9.4 | 三类元信息：`additional_kwargs`/`response_metadata`/`usage_metadata`（对应第 1 章字段） |
| 9.5 | `trim_messages`、消息合并、多模态内容块 |
| 9.6 | 流式 `.stream()`/`.astream()`；与第 31 章 SSE 对接 |
| 9.7 | `with_structured_output` 三策略；与第 4 章五种做法对照 |

示例：一次调用 + 元信息全打印；三策略结构化输出；`trim_messages` 前后 token。

**第 10 章 · LangChain 组合：LCEL、解析器、模板**

| 节 | 内容 |
|---|---|
| 10.1 | Runnable 协议：`invoke`/`batch`/`stream`/`astream_events` |
| 10.2 | 组合子：`|`、`RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableBranch`、`with_fallbacks`、`with_retry` |
| 10.3 | 模板：`ChatPromptTemplate`、`MessagesPlaceholder`、`FewShotChatMessagePromptTemplate` |
| 10.4 | 解析器：`StrOutputParser`/`JsonOutputParser`/`PydanticOutputParser`/`CommaSeparatedListOutputParser` |
| 10.5 | 自愈：`OutputFixingParser`/`RetryOutputParser` |
| 10.6 | 调试：`astream_events` 看每一步 |

示例：七个组合子；四解析器 + 自愈；事件流。

**第 11 章 · LangChain 工具**

| 节 | 内容 |
|---|---|
| 11.1 | `@tool`/`BaseTool`/`StructuredTool`；`args_schema`（pydantic） |
| 11.2 | `bind_tools`/`tool_choice`/并行 `tool_calls`；与第 6 章手写往返对照 |
| 11.3 | 注入：`InjectedState`/`InjectedStore`/`ToolRuntime` |
| 11.4 | 工具错误与重试：异常回灌、超时 |
| 11.5 | 工具收窄：允许列表与中间件过滤；与第 28 章护栏对照 |

示例：三种工具定义；`bind_tools` 往返；注入 state 的工具；异常回灌。

**第 12 章 · LangChain Agent：`create_agent` 与中间件**

| 节 | 内容 |
|---|---|
| 12.1 | `create_agent` 全参数（model/tools/system_prompt/state_schema/checkpointer/middleware） |
| 12.2 | 六个钩子与洋葱顺序；短路规则 |
| 12.3 | 内置中间件：摘要、HITL、PII、工具选择、重试、子代理等（逐个参数） |
| 12.4 | 自定义中间件的三个限制 |
| 12.5 | 与第 7 章手写循环逐项对照 |
| 12.6 | **过渡到 RAG**：agent 的工具有了、循环有了，但它答不了"我们自己的文档里怎么写的"；LangChain 在 RAG 上提供了哪些组件（预告第 13–21 章） |

示例：最小 agent；带 PII + HITL 中间件；洋葱顺序打印；"缺知识"的失败演示。

---

## 四、RAG 九章逐节（LangChain 的 RAG 组件）

**第 13 章 · 分流：不是所有请求都值得检索**

| 节 | 内容 |
|---|---|
| 13.1 | 三类请求与判据；误分流的两侧代价 |
| 13.2 | 规则路由：关键词/正则/长度 |
| 13.3 | 向量路由：`HuggingFaceEmbeddings` + 意图质心 + 阈值 |
| 13.4 | 兜底与置信度；兜底率报表 |

> 本章是 RAG 卷唯一不以 LangChain 链路为主的一章（路由发生在检索之前，LangChain 无对应抽象）。

**第 14 章 · RAG 的四个环节**

| 节 | 内容 |
|---|---|
| 14.1 | 检索/拼装/生成/引用四段为什么分开 |
| 14.2 | 检索的两类失败 |
| 14.3 | 拼装的三种坏法 |
| 14.4 | 生成的约束写在拼装里 |
| 14.5 | 引用：三个作用、三段分工、引用率与正确率 |
| 14.6 | 一次坏回答的四步归因 |

示例：LangChain 端到端 pipeline（`Document` → `TextSplitter` → `VectorStore` → `Retriever` → `PromptTemplate` → `ChatOpenAI` → 引用校验）。

**第 15 章 · 向量化**

| 节 | 内容 |
|---|---|
| 15.1 | 嵌入是什么；`HuggingFaceEmbeddings` |
| 15.2 | 归一化与距离；LangChain `distance_strategy` |
| 15.3 | 相似度读数与阈值；`similarity_score_threshold` |
| 15.4 | 维度与成本（bge 512 维实测） |
| 15.5 | 截断：`max_seq_length` 与块长联动 |
| 15.6 | 查询侧与文档侧：`embed_query` vs `embed_documents` |
| 15.7 | 稀疏 vs 稠密：`BM25Retriever` |
| 15.8 | 批量与缓存 |

示例：相似度矩阵；正负例分数分布；维度/截断对比。

**第 16 章 · 切块**

| 节 | 内容 |
|---|---|
| 16.1 | 块是检索最小单位；切错三后果 |
| 16.2 | `CharacterTextSplitter`（定长 + overlap） |
| 16.3 | `RecursiveCharacterTextSplitter` |
| 16.4 | `MarkdownHeaderTextSplitter`/`HTMLHeaderTextSplitter` |
| 16.5 | 按 token 切：`from_tiktoken_encoder` |
| 16.6 | `SemanticChunker`（语义切块） |
| 16.7 | 父子块：`ParentDocumentRetriever` |
| 16.8 | 表格/代码块；切块与截断联动 |

示例：五种切法块数与边界；语义切块对比；父子回取。

**第 17 章 · 向量数据库**

| 节 | 内容 |
|---|---|
| 17.1 | 向量库职责与 LangChain `VectorStore` 契约 |
| 17.2 | 三种索引：Flat/IVF/HNSW 及参数 |
| 17.3 | 距离与索引匹配 |
| 17.4 | `filter` 元数据过滤；预过滤 vs 后过滤 |
| 17.5 | 多租户隔离（collection/namespace/payload） |
| 17.6 | `add_documents`/`delete`/软删/重建 |
| 17.7 | 持久化、分片、副本、量化 |
| 17.8 | 选型：`QdrantVectorStore`/`Chroma`/`FAISS`/`PGVector` |

示例：Qdrant 建库写入；三种索引配置对比；filter 前后；持久化重载。

**第 18 章 · 检索质量**

| 节 | 内容 |
|---|---|
| 18.1 | 稠密与稀疏互补；`EnsembleRetriever` |
| 18.2 | RRF 与 `weights` 参数 |
| 18.3 | 重排：`ContextualCompressionRetriever` + `CrossEncoderReranker` |
| 18.4 | 改写：`MultiQueryRetriever`、HyDE 风格 |
| 18.5 | MMR：`search_type="mmr"` 的 λ |
| 18.6 | 指标：recall@k、MRR、nDCG |
| 18.7 | 何时不该加第二路/重排 |

示例：双路 + RRF；重排前后；MMR 去重；指标计算。

**第 19 章 · 上下文装配**

| 节 | 内容 |
|---|---|
| 19.1 | 四槽位预算与抢占 |
| 19.2 | `trim_messages` + `tiktoken` 计数 |
| 19.3 | 多块拼接：编号、去重、顺序 |
| 19.4 | 压缩：`LLMChainExtractor`/摘要 |
| 19.5 | 装配可观测：占用表与截断标记 |

**第 20 章 · 长期记忆**

| 节 | 内容 |
|---|---|
| 20.1 | 三层记忆与 RAG 的区别 |
| 20.2 | `VectorStore` 存记忆；元数据（租户/时间/来源） |
| 20.3 | 召回：改写 + 时间衰减 + 租户过滤 |
| 20.4 | 软删除与遗忘（`delete` 幂等） |
| 20.5 | 记忆污染：什么不该进长期记忆 |

**第 21 章 · 知识治理**

| 节 | 内容 |
|---|---|
| 21.1 | 改/删/版本共存；`Document.metadata` |
| 21.2 | 增量更新：按 doc_id 删旧插新 |
| 21.3 | 检索过滤失效块（写进 `VectorStore` 查询） |
| 21.4 | 缓存键带索引版本（接第 42 章） |
| 21.5 | 矛盾检测、条目化、可溯源率 |

---

## 五、其余框架（逐节）

### LangGraph（36–38）
36 图与状态：`StateGraph`、`MessagesState`、reducer、条件边、`Send`/`Command`、`compile`、函数式 API。
37 持久化/中断/流式：`Checkpointer` 家族、`thread_id`、时间旅行、`interrupt()`、5 种 `stream_mode`、`astream_events`。
38 多智能体编排：supervisor/swarm/hierarchical、handoff 两种实现、子图隔离、跨 agent trace 与成本。

### LlamaIndex（39–40）
39 基础与索引：Document/Node、`IngestionPipeline`、NodeParser、四种索引、存储与持久化。
40 RAG 与 Workflow：`QueryEngine`、响应合成器与引用、`Workflow`、与第 21 章（LangChain RAG）三版对照。

### 其他技术栈与平台（41）
Deep Agents / pydantic-ai / OpenAI Agents SDK / AutoGen / CrewAI / Coze·Dify（五节）。

### 并入主题的技术栈
- **42 计量与可观测**：先手写 span/OTel 约定，再 `opentelemetry-sdk` + `langfuse` 重做同一棵树。
- **43 RAG 评测**：先手算四指标，再讲评测集，最后 `ragas` 复算对比。
- **44 Agent 评测**：四层判据 + LangSmith/DeepEval/inspect_ai。

---

## 六、概念清查去向（按 v10 章号）

| 域 | 概念 | 判定 | 去向 |
|---|---|---|---|
| 模型 | token/分词器 | 不足 | 3 章 + `tiktoken` |
| 模型 | chat template / 特殊 token | **缺失** | 3 章 |
| 模型 | KV cache | **缺失** | 3 章 |
| 模型 | 多模态 / logprobs | 不足 | 1 章 / 2 章 |
| 模型 | 结构化输出五法 | 不足 | 4 章（+9.7 对照） |
| Agent | 并行工具调用 | 不足 | 6 章 |
| Agent | 工具注入/收窄 | **缺失** | 11 章 |
| Agent | MCP（换 SDK） | 不足 | 26 章 |
| Agent | 范式/反思/状态/持久化 | 覆盖 | 22–25 章 |
| RAG | 文档解析（PDF/表格） | **缺失** | 14 章 |
| RAG | 切块（五种 + token/语义/父子/表格） | 覆盖但代码假 | 16 章 |
| RAG | 嵌入原理/距离/读数/维度/截断/查询侧/批量 | **缺失或不足** | 15 章 |
| RAG | 向量库职责/HNSW/IVF-PQ/过滤/多租户/持久化/选型 | **缺失** | 17 章 |
| RAG | 混合/RRF/重排/改写 | 覆盖但代码假 | 18 章 |
| RAG | MMR / MRR / nDCG | **缺失** | 18 章（+43 章） |
| RAG | 装配/记忆/治理 | 覆盖但代码假 | 19–21 章 |
| 约束 | 沙箱/护栏/注入/审批/交付 | 覆盖 | 27–32 章 |
| 度量 | span/OTel/落盘 | 不足 | 42 章（真 SDK） |
| 度量 | LangFuse | **缺失** | 42 章 |
| 度量 | 评测集 / RAGAS | **缺失** | 43 章 |
| 度量 | Agent 评测框架 | **缺失** | 44 章 |
| 度量 | 统计/门禁/成本/延迟/复盘 | 覆盖 | 45–46 章 |
| 工程 | **pydantic / Settings** | **缺失** | **5 章** |

---

## 七、代码实例清单

| 章 | 补什么 | 关键库 |
|---|---|---|
| 1–6 | 真实响应、分词、结构化输出、pydantic、工具往返 | `openai`（回放）、`tiktoken`、`pydantic` |
| 9–12 | LangChain agent 侧四章 | `langchain`、`langchain-openai` |
| 13 | 路由 + 兜底率（唯一非 LangChain 章） | `sentence-transformers` |
| 14 | 端到端 pipeline + 引用校验 | `langchain`、`langchain-qdrant`、`langchain-huggingface` |
| 15 | 相似度矩阵、维度/截断 | `langchain-huggingface` |
| 16 | 五种切块器、父子检索 | `langchain-text-splitters` |
| 17 | 三种索引、过滤、持久化 | `langchain-qdrant`、`langchain-community` |
| 18 | 双路+RRF+重排+MMR+指标 | `langchain`、`langchain-community`（BM25）、`sentence-transformers` |
| 19 | 三种装配与 token 表 | `langchain`、`tiktoken` |
| 20–21 | 记忆与治理 | `langchain`、`langchain-qdrant` |
| 22–26 | 手写为主；26 换 `mcp` SDK | `mcp` |
| 27–32 | 手写为主；28 补中间件、30 补 `interrupt()` | `langchain`、`langgraph` |
| 33–35 | 拆分/A2A/手写编排 | `a2a-sdk` |
| 36–38 | LangGraph 三章 | `langgraph` |
| 39–40 | LlamaIndex 两章 | `llama-index` |
| 41 | 其他栈 | `pydantic-ai`、`openai-agents` |
| 42 | OTel + LangFuse | `opentelemetry-sdk`、`langfuse` |
| 43 | 真实嵌入 + 评测集 + RAGAS | `ragas`、`sentence-transformers` |
| 44 | Agent 评测框架 | 见 41 章 |
| 47–51 | 副线 | 标准库 |

---

## 八、执行批次

| 批 | 章 | 验收 |
|---|---|---|
| 0 | 全库重排为 52 章 | 引用扫描 0 错、脚本跑通 |
| 1 | 9、10、11、12 | LangChain agent 侧四章可跑，含过渡节 |
| 2 | 13、14、15 | 分流、端到端、向量化 |
| 3 | 16、17、18 | 切块/向量库/检索质量（全 LangChain） |
| 4 | 19、20、21 | 装配/记忆/治理 |
| 5 | 42、43、44 | LangFuse + RAGAS + 评测框架 |
| 6 | 33–35 | A2A + 手写编排 |
| 7 | 36–38 | LangGraph 三章 |
| 8 | 39–41 | LlamaIndex 与平台 |
| 9 | 1–6、22–32 补齐 | 每章至少一处真库 |
| 10 | 47–51 | 副线 |

**硬规则**：① 示例最多 3 次，失败写"环境限制"；② RAG 卷（13–21）不得出现手写向量/检索代码（13 章除外）；③ 框架章按列出的节写，不压缩。

---

## 九、待确认

1. 第 12 章末尾的"过渡到 RAG"一节是否合适（先演示"agent 缺知识"的失败，再预告 LangChain 的 RAG 组件）？
2. 第 13 章"分流"保留为非 LangChain 章，是否接受？
3. 第 1、2、4、6 章无 key，是否允许本地 OpenAI 兼容回放服务器？
