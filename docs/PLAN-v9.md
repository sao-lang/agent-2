# 改造方案 v9：LangChain 与 RAG 合并讲授

> 取代 v7/v8。本版按最新要求重排：
> 1. **LangChain 不再单独成段**，直接与 RAG 一起讲：LangChain 的入门章放在 RAG 卷开头，之后每个 RAG 环节都用 LangChain 实现。
> 2. **RAG 卷里的代码实例统一用 LangChain**（切块、嵌入、向量库、检索、装配、记忆、治理、agent）。
> 3. 基础概念仍然先讲（文字 + 失效分析），但代码从手写改为 LangChain——概念与代码不再各讲一套。
> 4. 进阶（范式/反思/状态/持久化）与工程化仍在 RAG 之后；多智能体、LangGraph 再后。
> 5. 框架能力不能压缩：LangChain 在 RAG 卷里占 1 章入门 + 各章实现 + 1 章搭 agent。

---

## 一、总原则

| # | 原则 | 做法 |
|---|---|---|
| 1 | 概念先讲 | 每章先讲"是什么/不做会怎么坏"，再给 LangChain 实现 |
| 2 | 代码统一 | RAG 卷所有示例用 LangChain 的抽象（`Document`/`TextSplitter`/`Embeddings`/`VectorStore`/`Retriever`/`Chain`） |
| 3 | 框架成组 | LangChain 全在 RAG 卷；LangGraph 最后单独三章；LlamaIndex 最后两章 |
| 4 | 不压缩 | 每章按下方列出的节写，不允许合并小节 |
| 5 | 进阶后置 | 范式/反思/状态/持久化/MCP·Skill 在 RAG 之后 |
| 6 | 部件库只在非 RAG 章 | `tiktoken`/`pydantic`/`mcp`/`a2a-sdk`/`opentelemetry-sdk` 用在这些主题章；RAG 卷一律 LangChain |

---

## 二、全书结构（50 章，0–49）

| 卷 | 名称 | 章 | 说明 |
|---|---|---|---|
| 0 | 起点 | 0 | agent 是什么 |
| 1 | 一次调用 | 1–5 | 四字段 / 编与忘 / token 成本 / 结构化输出 / pydantic |
| 2 | 最小 agent | 6–8 | 工具 / 循环 / 终止与失控 |
| 3 | **RAG 与 LangChain** | 9–19 | 分流 → LangChain 入门 → 四环节 → 向量化 → 切块 → 向量库 → 检索质量 → 装配 → 记忆 → 治理 → 搭 agent |
| 4 | agent 进阶 | 20–24 | 范式 / 反思 / 状态 / 持久化 / MCP·Skill |
| 5 | agent 工程化 | 25–30 | 沙箱 / 护栏 / 注入 / 审批 / 对外形态 / 交付 |
| 6 | 多智能体 | 31–33 | 拆分与协作 / A2A / 手写编排 |
| 7 | LangGraph | 34–36 | 图与状态 / 持久化与流式 / 多智能体编排 |
| 8 | 其他框架 | 37–39 | LlamaIndex 两章 / 其他技术栈与平台 |
| 9 | 度量与复盘 | 40–44 | 计量（OTel+LangFuse）/ RAG 评测（RAGAS）/ Agent 评测 / 门禁 / 成本延迟 |
| 10 | 组件封装（副线） | 45–49 | 契约与替换实验 |

知识点：A9 + B21 + **C14** + **D16** + E14 + F18 + **H14** + G5 = **111 条**。

---

## 三、RAG 卷：11 章逐节清单（代码全部 LangChain）

### 第 9 章 · 分流：不是所有请求都值得检索

| 节 | 内容 |
|---|---|
| 9.1 | 三类请求（寒暄/常识/需检索）与判据；误分流的两侧代价 |
| 9.2 | 规则路由：关键词/正则/长度 |
| 9.3 | 向量路由：查询嵌入 + 意图质心 + 阈值 |
| 9.4 | 兜底与置信度：路由失败时走完整循环 |
| 9.5 | 兜底率报表：误分流怎么归因 |

示例：规则路由 + `HuggingFaceEmbeddings`（bge）意图质心路由 + 兜底率统计。**这一章是唯一允许不用 LangChain 的 RAG 章**（路由发生在检索之前，LangChain 无对应抽象）。

### 第 10 章 · LangChain 入门：模型、消息、组合子

| 节 | 内容 |
|---|---|
| 10.1 | 包结构：`langchain-core`/`langchain`/`langchain-openai`/`langchain-community`；版本边界 |
| 10.2 | `init_chat_model` 参数矩阵；OpenAI 兼容端点（`base_url`） |
| 10.3 | 四种消息与三类元信息（对应第 1 章字段） |
| 10.4 | `PromptTemplate`/`ChatPromptTemplate`/`MessagesPlaceholder` |
| 10.5 | Runnable 协议与组合子：`|`、`RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableBranch`、`with_fallbacks`、`with_retry` |
| 10.6 | 输出解析器：`StrOutputParser`/`JsonOutputParser`/`PydanticOutputParser`/`CommaSeparatedListOutputParser`；`OutputFixingParser` 自愈 |
| 10.7 | 流式 `.stream()`/`.astream_events()`；与第 29 章 SSE 对接 |
| 10.8 | `with_structured_output` 三策略，与第 4 章五种做法对照 |

示例：一次调用 + 元信息打印；七个组合子；四解析器 + 自愈；事件流打印。

### 第 11 章 · RAG 的四个环节

| 节 | 内容 |
|---|---|
| 11.1 | 检索/拼装/生成/引用四段为什么要分开 |
| 11.2 | 检索的两类失败（没召回/召回噪声） |
| 11.3 | 拼装的三种坏法与预算 |
| 11.4 | 生成的约束写在拼装里 |
| 11.5 | 引用：三个作用、三段分工、引用率与引用正确率 |
| 11.6 | 一次坏回答的四步归因 |

示例：**LangChain 端到端 pipeline**：`Document` → `TextSplitter` → `VectorStore` → `Retriever` → prompt（带引用编号）→ `ChatOpenAI`（回放）→ 逐句引用校验。

### 第 12 章 · 向量化：嵌入的原理

| 节 | 内容 |
|---|---|
| 12.1 | 嵌入是什么：文本→向量空间；`HuggingFaceEmbeddings` 的封装 |
| 12.2 | 归一化与距离：cosine/dot/L2；LangChain 里 `distance_strategy` 怎么选 |
| 12.3 | 相似度读数：正/负例分布、阈值、`similarity_score_threshold` |
| 12.4 | 维度与成本：bge-small-zh 512 维实测（存储/延迟） |
| 12.5 | 截断：`max_seq_length` 与块长的联动 |
| 12.6 | 查询侧与文档侧：bge 的 query instruction；`embed_query` vs `embed_documents` |
| 12.7 | 稀疏 vs 稠密：`BM25Retriever` 为什么仍要一路 |
| 12.8 | 批量与缓存：`embed_documents(batch_size=...)`、失败重试 |

示例：同一批句子的相似度矩阵；三句正负例的分数分布；512 维 vs 768 维的存储对比；截断前后召回变化。

### 第 13 章 · 切块

| 节 | 内容 |
|---|---|
| 13.1 | 块是检索最小单位；切错的三种后果 |
| 13.2 | 字符切：`CharacterTextSplitter`（定长 + overlap） |
| 13.3 | 递归切：`RecursiveCharacterTextSplitter`（分隔符优先级） |
| 13.4 | 结构切：`MarkdownHeaderTextSplitter`、`HTMLHeaderTextSplitter` |
| 13.5 | token 切：按 token 计数切；与第 3 章分词器衔接 |
| 13.6 | 语义切：`SemanticChunker`（按嵌入相似度断句）与成本 |
| 13.7 | 父子块与"检索用小、生成用大"：`ParentDocumentRetriever` |
| 13.8 | 表格/代码块处理；切法与嵌入截断的联动 |

示例：五种切法在同一文档上的块数与边界；`SemanticChunker` 与递归切的对比；父子检索的回取。

### 第 14 章 · 向量数据库

| 节 | 内容 |
|---|---|
| 14.1 | 向量库职责：存储/索引/过滤/持久化；LangChain 的 `VectorStore` 契约 |
| 14.2 | 三种索引：Flat、IVF（`nlist`/`nprobe`）、HNSW（`M`/`efConstruction`/`efSearch`） |
| 14.3 | 距离度量与索引匹配；归一化后 cosine 与 dot 等价 |
| 14.4 | 元数据过滤：`filter` 参数、预过滤 vs 后过滤 |
| 14.5 | 多租户：collection / namespace / payload 三种隔离 |
| 14.6 | 写入语义：`add_documents`/`delete`/软删/重建 |
| 14.7 | 运维：持久化、快照、分片、副本、量化 |
| 14.8 | 选型：`Qdrant`/`Chroma`/`FAISS`/`pgvector` 在 LangChain 里的接入差异 |

示例：`QdrantVectorStore` 建库与写入；Flat/IVF/HNSW 三种配置的耗时与召回；payload 过滤前后结果；持久化后再加载。

### 第 15 章 · 检索质量：混合、重排、改写

| 节 | 内容 |
|---|---|
| 15.1 | 稠密与稀疏的互补；`EnsembleRetriever` + `BM25Retriever` |
| 15.2 | RRF 融合原理与 `EnsembleRetriever(weights=...)` 的参数含义 |
| 15.3 | 重排：`ContextualCompressionRetriever` + `CrossEncoderReranker`（bge-reranker） |
| 15.4 | 查询改写：`MultiQueryRetriever`、`HyDE` 风格改写 |
| 15.5 | MMR：`as_retriever(search_type="mmr")` 的 λ 与效果 |
| 15.6 | 检索指标：recall@k、MRR、nDCG 怎么算 |
| 15.7 | 什么时候不该加第二路/重排（成本与收益） |

示例：BM25 与向量双路 + RRF；CrossEncoder 重排前后 Top-5；MMR 前后的重复块数；MRR/nDCG 计算。

### 第 16 章 · 上下文装配

| 节 | 内容 |
|---|---|
| 16.1 | 四槽位预算（系统/任务/资料/输出）与抢占顺序 |
| 16.2 | `trim_messages` 与按 token 计数（`tiktoken`） |
| 16.3 | 多块拼接：编号、去重、顺序（相关度 vs 原文顺序） |
| 16.4 | 压缩：`LLMChainExtractor`/摘要中间件 |
| 16.5 | 装配的可观测：占用表与截断标记 |

示例：同一批候选的三种装配（全量/截断/压缩）与最终 prompt 的 token 表。

### 第 17 章 · 长期记忆

| 节 | 内容 |
|---|---|
| 17.1 | 三层记忆：语义/情景/程序；与 RAG 的区别 |
| 17.2 | 写入：`VectorStore` 存记忆、元数据带租户与时间 |
| 17.3 | 召回：查询改写 + 时间衰减 + 租户过滤 |
| 17.4 | 软删除与遗忘：`delete` 的幂等 |
| 17.5 | 记忆污染：什么不该进长期记忆（第 31 章注入的延伸） |

示例：三层记忆写入 + 带租户过滤的召回；遗忘前后的检索结果。

### 第 18 章 · 知识治理与文档生命周期

| 节 | 内容 |
|---|---|
| 18.1 | 改/删/版本共存；`Document.metadata` 带版本与来源 |
| 18.2 | 增量更新：按文档 ID 删旧插新；`delete(filter=...)` |
| 18.3 | 检索必须过滤失效：把过滤写进 `VectorStore` 查询 |
| 18.4 | 缓存与索引版本：语义缓存键要带版本（接第 40 章） |
| 18.5 | 矛盾检测与条目化；可溯源率 |

示例：v1→v2 版本替换；失效块过滤前后；两条矛盾条目的检测。

### 第 19 章 · 用 LangChain 搭 agent

| 节 | 内容 |
|---|---|
| 19.1 | `create_agent` 全参数（model/tools/system_prompt/state_schema/checkpointer/middleware） |
| 19.2 | 工具：`@tool`、`args_schema`、`bind_tools`、并行 `tool_calls` |
| 19.3 | 六个钩子与洋葱顺序；短路规则 |
| 19.4 | 内置中间件：摘要、HITL、PII、工具选择、重试、子代理等（逐个参数） |
| 19.5 | 把 RAG 做成一个工具接进 agent：`retriever_tool` |
| 19.6 | 与第 7 章手写循环逐项对照：终止、状态、预算、审批 |
| 19.7 | 边界：什么时候该手写循环 |

示例：带检索工具的 agent；加 PII 与 HITL 中间件；洋葱顺序打印。

---

## 四、其余框架章（逐节）

### LangGraph（第 34–36 章）

**34 图与状态**：`StateGraph`、`MessagesState`、reducer、`add_conditional_edges`、`Send`、`Command`、`compile`、函数式 API；与第 22 章手写 State 对照。
**35 持久化、中断与流式**：`Checkpointer` 家族、`thread_id`、`get_state_history`、`update_state`、`interrupt()`、5 种 `stream_mode`、`astream_events`。
**36 多智能体编排**：supervisor/swarm/hierarchical、handoff（工具式 vs `Command`）、子图与上下文隔离、跨 agent trace 与成本。

### LlamaIndex（第 37–38 章）

**37 基础与索引**：Document/Node、`IngestionPipeline`、NodeParser、四种索引、存储与持久化。
**38 RAG 与 Workflow**：`QueryEngine`（retrieve→postprocess→synthesize）、响应合成器与引用、`Workflow`、与 LangChain 版（第 19 章）对照。

### 其他技术栈与平台（第 39 章）

Deep Agents（九组件/沙箱/权限/技能/容错）、pydantic-ai（类型化 agent/TestModel/evals）、OpenAI Agents SDK（handoff/guardrail/session）、AutoGen/CrewAI、Coze/Dify（三类隐形状态与导出边界）。

### 并入主题的技术栈

- **40 计量与可观测**：先讲 span/OTel 约定（手写），再用 `opentelemetry-sdk` + `langfuse` 重做同一棵树。
- **41 RAG 评测**：先手算四指标（真实嵌入），再讲评测集（抽样/合成/覆盖矩阵/版本化），最后用 `ragas` 复算并对比。
- **42 Agent 评测**：四层判据（结果/轨迹/稳定/成本）+ LangSmith experiments / DeepEval / inspect_ai 跑同一批用例。

---

## 五、概念清查清单（去向按 v9 章号）

| 域 | 概念 | 判定 | 去向 |
|---|---|---|---|
| 模型 | token 与分词器 | 不足 | 3 章 + `tiktoken` |
| 模型 | chat template / 特殊 token | **缺失** | 3 章 |
| 模型 | KV cache | **缺失** | 3 章 |
| 模型 | 多模态 | 不足 | 1 章 |
| 模型 | logprobs | 不足 | 2 章 |
| 模型 | 结构化输出五法 | 不足 | 4 章（+10.8 对照） |
| Agent | 并行工具调用 | 不足 | 6 章 |
| Agent | 工具注入 / 工具收窄 | **缺失** | 19 章（LangChain） |
| Agent | MCP（手写→SDK） | 不足 | 24 章 |
| Agent | 编排/反思/状态/持久化 | 覆盖 | 20–23 章 |
| RAG | 文档解析（PDF/表格） | **缺失** | 11 或 13 章 |
| RAG | 切块五法（手写→LangChain） | 覆盖但代码假 | 13 章 |
| RAG | token/语义/表格切块 | **缺失** | 13 章 |
| RAG | 嵌入原理/归一化/距离/读数/维度/截断/查询侧/批量 | **缺失或不足** | 12 章 |
| RAG | 向量库职责/HNSW/IVF-PQ/过滤/多租户/持久化/分片/量化/选型 | **缺失** | 14 章 |
| RAG | 混合/RRF/重排/改写 | 覆盖但代码假 | 15 章 |
| RAG | MMR | **缺失** | 15 章 |
| RAG | MRR/nDCG | **缺失** | 15 章 + 41 章 |
| RAG | 装配/记忆/治理 | 覆盖但代码假 | 16–18 章 |
| 约束 | 沙箱/护栏/注入/审批/交付 | 覆盖 | 25–30 章 |
| 度量 | span/OTel/落盘/采样 | 不足 | 40 章（真 SDK） |
| 度量 | LangFuse | **缺失** | 40 章 |
| 度量 | 评测集 / RAGAS | **缺失** | 41 章 |
| 度量 | Agent 评测框架 | **缺失** | 42 章 |
| 度量 | 统计/门禁/成本/延迟/复盘 | 覆盖 | 43–44 章 |
| 工程 | **pydantic / Settings** | **缺失** | **5 章** |

---

## 六、代码实例清单（RAG 卷全部 LangChain）

| 章 | 补什么 | 关键库 |
|---|---|---|
| 1–6 | 真实响应、分词、结构化输出、pydantic、工具往返 | `openai`（回放）、`tiktoken`、`pydantic` |
| 9 | 路由 + 兜底率 | `sentence-transformers`（唯一非 LangChain 的 RAG 章） |
| 10 | LangChain 入门全套 | `langchain`、`langchain-openai` |
| 11 | 端到端 pipeline + 引用校验 | `langchain`、`langchain-qdrant`、`langchain-huggingface` |
| 12 | 相似度矩阵、维度/截断实验 | `langchain-huggingface`（`HuggingFaceEmbeddings`） |
| 13 | 五种切块器对比、父子检索 | `langchain-text-splitters`、`langchain`（`ParentDocumentRetriever`） |
| 14 | 三种索引、过滤、持久化 | `langchain-qdrant`、`langchain-community`（FAISS/Chroma） |
| 15 | 双路 + RRF + CrossEncoder + MMR + 指标 | `langchain`、`rank_bm25`（经 `BM25Retriever`）、`sentence-transformers` |
| 16 | 三种装配与 token 表 | `langchain`、`tiktoken` |
| 17 | 三层记忆 | `langchain`、`langchain-qdrant` |
| 18 | 版本过滤与增量 | `langchain`、`langchain-qdrant` |
| 19 | 带检索工具的 agent + 中间件 | `langchain` |
| 20–30 | 手写为主；24 换 `mcp`、26 补中间件、28 补 `interrupt()` | `mcp`、`langchain`、`langgraph` |
| 31–33 | 拆分/A2A/手写编排 | `a2a-sdk` |
| 34–36 | LangGraph 三章 | `langgraph` |
| 37–38 | LlamaIndex 两章 | `llama-index` |
| 39 | 其他栈 | `pydantic-ai`、`openai-agents` |
| 40 | OTel + LangFuse | `opentelemetry-sdk`、`langfuse` |
| 41 | 真实嵌入 + 评测集 + RAGAS | `ragas`、`sentence-transformers` |
| 42 | Agent 评测框架 | 见 39 章 |
| 45–49 | 副线 | 标准库 |

---

## 七、执行批次

| 批 | 章 | 验收 |
|---|---|---|
| 0 | 全库重排为 50 章 | 引用扫描 0 错、脚本跑通 |
| 1 | 10、11、12 | LangChain 入门 + 端到端 + 向量化 |
| 2 | 13、14、15 | 切块/向量库/检索质量三章全 LangChain |
| 3 | 16、17、18、19 | 装配/记忆/治理/agent |
| 4 | 40、41、42 | LangFuse + RAGAS + 评测框架 |
| 5 | 31–33 多智能体 | A2A 往返 + 手写编排 |
| 6 | 34–36 LangGraph | 三个图 |
| 7 | 37–39 LlamaIndex 与其他 | 每框架最小可跑 |
| 8 | 1–6、9、20–30 补齐 | 每章至少一处真库 |
| 9 | 45–49 副线 | 替换实验 |

**硬规则**：① 示例最多 3 次，失败写"环境限制"；② RAG 卷不得出现手写向量/检索代码（除分流章）；③ 框架章按第三节的节写，不压缩。

---

## 八、待确认

1. 第 9 章"分流"保留为非 LangChain 章（路由在检索之前），是否接受？
2. 第 19 章"用 LangChain 搭 agent"放在 RAG 卷末尾，还是移到卷 4 进阶里？
3. 第 1、2、4、6 章无 API key，是否允许本地 OpenAI 兼容回放服务器？
