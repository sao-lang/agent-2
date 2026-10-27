# 改造方案 v8：基础先行、框架成组、内容列到节

> 取代 `docs/PLAN-v7.md`。本版按五条修正重做：
> 1. LangChain 不能一章带过——**用 4 章**讲清特性与 API，最后落到"用 LangChain 搭 agent"。
> 2. **先基础、后框架**，顺序不能反。
> 3. 每个框架要讲的内容**逐节列出**，不许"到时候再展开"。
> 4. 框架使用**至少 1 章/主题**，防止压缩。
> 5. **编排范式、反思、状态、持久化**等进阶内容移到 RAG 之后，与工程化合并；讲完再讲**多智能体**与 **LangGraph**。

---

## 一、总原则

| # | 原则 | 具体做法 |
|---|---|---|
| 1 | 基础先行 | 每一块都是"概念 → 失效 → 最小示例"讲完，才允许出现对应框架章 |
| 2 | 框架成组 | 同一框架的章节连续排列，不与其他框架交错；LangChain 一组、LangGraph 一组、LlamaIndex 一组 |
| 3 | 框架章也要列到节 | 每个框架章在方案里就写清小节与 API，写作时不得合并压缩 |
| 4 | 进阶后置 | 编排范式/反思/状态/持久化/MCP·Skill 放到 RAG 之后，与工程化（沙箱/护栏/审批/交付）成卷 |
| 5 | 技术栈并入主题 | 可观测=OTel+LangFuse；RAG 评测=指标+评测集+RAGAS；Agent 评测=四层+评测框架；各自一章内"先概念后工具" |
| 6 | 部件库 vs 框架 | 基础章可用部件库（tiktoken/pydantic/bge/qdrant/rank_bm25/mcp/a2a-sdk）；框架只在框架章出现 |

---

## 二、全书结构（53 章，0–52）

| 卷 | 名称 | 章 | 一句话 |
|---|---|---|---|
| 0 | 起点 | 0 | agent 是什么 |
| 1 | 一次调用 | 1–5 | 模型层最小单位 + 契约（pydantic） |
| 2 | 最小 agent | 6–8 | 工具、循环、怎么停 |
| 3 | **LangChain 四章** | 9–12 | 特性与 API 讲透，最后搭出 agent |
| 4 | RAG | 13–22 | 分流、四环节、向量化、切块、向量库、检索、装配、记忆、治理 + **LangChain 的 RAG 实现** |
| 5 | agent 进阶 | 23–27 | 范式、反思、状态、持久化、MCP·Skill |
| 6 | agent 工程化 | 28–33 | 沙箱、护栏、注入、审批、对外形态、交付 |
| 7 | 多智能体 | 34–36 | 拆分与协作、A2A、手写编排 |
| 8 | **LangGraph 三章** | 37–39 | 图与状态、持久化与流式、多智能体编排 |
| 9 | 其他框架 | 40–42 | LlamaIndex 两章 + 其他技术栈与平台一章 |
| 10 | 度量与复盘 | 43–47 | 计量（OTel+LangFuse）、RAG 评测（RAGAS）、Agent 评测、门禁、成本延迟 |
| 11 | 组件封装（副线） | 48–52 | 契约与替换实验 |

知识点：A9 + B21 + **C14**（新增向量化、向量数据库）+ **D16**（A2A）+ E14 + F18 + **H14**（pydantic）+ G5 = **111 条**。

---

## 三、框架章内容清单（逐节）

### 3.1 LangChain（第 9–12 章，四章）

**第 9 章 · LangChain 基础：包、模型、消息**

| 节 | 要讲的内容（API） |
|---|---|
| 9.1 | 包结构：`langchain-core` / `langchain` / 厂商包（`langchain-openai`）/ `langchain-community`；版本与依赖边界 |
| 9.2 | `init_chat_model` 参数矩阵：`model`/`model_provider`/`base_url`/`temperature`/`max_tokens`/`timeout`/`max_retries` |
| 9.3 | 四种消息：`SystemMessage`/`HumanMessage`/`AIMessage`/`ToolMessage`；`content` 与 `content_blocks` 的差别 |
| 9.4 | 三类元信息：`additional_kwargs`/`response_metadata`/`usage_metadata`，分别对应第 1 章的哪些字段 |
| 9.5 | 消息处理：`trim_messages`（按 token 裁剪）、消息合并、多模态内容块 |
| 9.6 | 流式：`.stream()` / `.astream()`，与第 28 章 SSE 的对接 |
| 9.7 | 结构化输出：`with_structured_output` 三种策略（`json_schema`/`function_calling`/`json_mode`），与第 4 章五种做法逐条对照 |
| 9.8 | 网关兼容：任何 OpenAI 兼容端点（`base_url`）怎么接；与第 1 章 HTTP 请求的对应 |

示例：一次真实调用（回放服务器）、消息元信息全打印、三策略结构化输出、`trim_messages` 前后 token。

**第 10 章 · LangChain 组合：LCEL、解析器、模板**

| 节 | 内容（API） |
|---|---|
| 10.1 | Runnable 协议：`invoke`/`batch`/`stream`/`astream_events`；输入输出契约 |
| 10.2 | 组合子：`|`、`RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableBranch`、`with_fallbacks`、`with_retry` |
| 10.3 | 提示词模板：`ChatPromptTemplate`、`MessagesPlaceholder`、`FewShotChatMessagePromptTemplate` |
| 10.4 | 输出解析器：`StrOutputParser`、`JsonOutputParser`、`PydanticOutputParser`、`CommaSeparatedListOutputParser` |
| 10.5 | 自愈：`OutputFixingParser`、`RetryOutputParser`，与第 4 章"校验失败回灌"的对应 |
| 10.6 | 链的调试：`astream_events` 看每一步的输入输出；与第 27 章 span 的关系 |

示例：七个组合子各一例；四种解析器 + 自愈闭环；事件流打印每一步。

**第 11 章 · LangChain 工具与检索**

| 节 | 内容（API） |
|---|---|
| 11.1 | 三种工具定义：`@tool`、`BaseTool` 子类、`StructuredTool`；`args_schema` 用 pydantic |
| 11.2 | `bind_tools`、`tool_choice`、并行 `tool_calls`；与第 6 章手写往返逐字对照 |
| 11.3 | 工具注入：`InjectedState`、`InjectedStore`、`ToolRuntime` |
| 11.4 | `VectorStore` 接口：`similarity_search`/`add_documents`/`delete` |
| 11.5 | `as_retriever` 三种 `search_type`：`similarity`、`mmr`、`similarity_score_threshold`；与第 18 章 MMR 对照 |
| 11.6 | 三个 Retriever 装饰器：`MultiQueryRetriever`、`ContextualCompressionRetriever`、`EnsembleRetriever`；与第 16、18 章对照 |

示例：三种工具定义；`bind_tools` 往返；三种 `search_type` 的结果差异；Ensemble 混合两路。

**第 12 章 · LangChain Agent：`create_agent` 与中间件**

| 节 | 内容（API） |
|---|---|
| 12.1 | `create_agent` 全参数：`model`/`tools`/`system_prompt`/`state_schema`/`context_schema`/`checkpointer`/`store`/`middleware` |
| 12.2 | 六个钩子与洋葱顺序：`before_model`/`after_model`/`before_tool`/`after_tool`/…；短路规则 |
| 12.3 | 内置中间件分类：限流、重试、摘要、HITL、PII、工具选择、子代理、rubric 等 19 个逐个参数 |
| 12.4 | 自定义中间件的三个限制（顺序、状态可见性、异常传播） |
| 12.5 | 与第 7 章手写循环逐项对照：终止、状态、预算、审批各落在哪 |
| 12.6 | 一个完整 agent：工具 + PII 中间件 + HITL 中间件 + 检查点 |

示例：最小 agent；带两个中间件的 agent；打印洋葱顺序的自定义中间件。

### 3.2 LangGraph（第 37–39 章，三章）

**第 37 章 · LangGraph 基础：状态与图**

| 节 | 内容 |
|---|---|
| 37.1 | `StateGraph`、状态定义（`TypedDict`/`Annotated[list, add]`）、`MessagesState` |
| 37.2 | `add_node`/`add_edge`/`add_conditional_edges` |
| 37.3 | `Send` 动态扇出、`Command` 跳转 + 更新 |
| 37.4 | `compile` 参数、`Pregel` 超步执行模型 |
| 37.5 | 函数式 API：`@entrypoint`/`@task`，与图 API 的取舍 |
| 37.6 | 与第 25 章手写 State、第 23 章编排范式逐项对照 |

**第 38 章 · LangGraph 持久化、中断与流式**

| 节 | 内容 |
|---|---|
| 38.1 | `Checkpointer` 家族：InMemory / Sqlite / Postgres；存了什么 |
| 38.2 | `thread_id` / `checkpoint_ns`；会话隔离 |
| 38.3 | `get_state_history` / `update_state`（时间旅行） |
| 38.4 | `interrupt()` 与恢复：人在环的两种形态；与第 31 章审批对照 |
| 38.5 | 5 种 `stream_mode`：values/updates/custom/messages/debug |
| 38.6 | `astream_events` v2 字段；与第 43 章 trace 的对接 |

**第 39 章 · LangGraph 多智能体编排**

| 节 | 内容 |
|---|---|
| 39.1 | supervisor / swarm / hierarchical 三种拓扑 |
| 39.2 | handoff 的实现：工具式 vs `Command` 式 |
| 39.3 | 子图与上下文隔离；与第 34 章拆分判据对照 |
| 39.4 | 共享状态与消息总线；并发写的 reducer |
| 39.5 | 跨 agent 的 trace 与成本归因（接第 35、43 章） |
| 39.6 | 与第 36 章手写编排的逐项对照 |

### 3.3 LlamaIndex（第 40–41 章，两章）

**第 40 章 · LlamaIndex 基础与索引**

| 节 | 内容 |
|---|---|
| 40.1 | 四个核心概念：Document/Node、Index、Retriever、QueryEngine |
| 40.2 | `IngestionPipeline` 与 NodeParser（与第 16 章切块对照） |
| 40.3 | 索引类型：Vector / Summary / Keyword / KnowledgeGraph 各自适用 |
| 40.4 | 存储：docstore/index_store/vector_store；持久化与重载 |
| 40.5 | 嵌入与 LLM 的接入方式；与第 15、17 章的对应 |

**第 41 章 · LlamaIndex 的 RAG 与 Workflow**

| 节 | 内容 |
|---|---|
| 41.1 | `QueryEngine` 的查询流程：retrieve → postprocess → synthesize |
| 41.2 | 响应合成器与引用；与第 14 章引用校验对照 |
| 41.3 | `Workflow`：事件驱动的多步 RAG |
| 41.4 | 同一批文档在 LlamaIndex 与第 22 章 LangChain 版的差异 |
| 41.5 | 边界：LlamaIndex 不擅长什么 |

### 3.4 其他技术栈与平台（第 42 章，一章但五节）

| 节 | 内容 |
|---|---|
| 42.1 | Deep Agents：九个内建组件、subagents、permissions、sandboxes、skills、fault-tolerance |
| 42.2 | pydantic-ai：类型化 agent、`TestModel`、pydantic-evals |
| 42.3 | OpenAI Agents SDK：handoff、guardrail、session |
| 42.4 | AutoGen / CrewAI：group chat、roles、与 supervisor 的差别 |
| 42.5 | Coze / Dify：三类隐形状态（会话、变量、知识库版本）、导出与锁定边界 |

### 3.5 并入主题的技术栈

| 章 | 技术栈 | 并入方式 |
|---|---|---|
| 43 计量与可观测 | `opentelemetry-sdk` + `langfuse` | 先讲 span/OTel 约定（手写版），再用两个 SDK 重做同一棵树 |
| 44 RAG 评测 | 指标 + 评测集 + `ragas` | 先手算四指标，再用 RAGAS 复算并对比；评测集独立一节 |
| 45 Agent 评测 | LangSmith experiments / DeepEval / inspect_ai | 先讲四层判据，再用框架跑同一批用例 |

---

## 四、概念清查清单（去向按新章号）

### 4.1 模型层

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| token 与分词器 | 有估算，无分词器原理 | 不足 | 3 章补一节 + `tiktoken` 实测 |
| chat template / 特殊 token | 无 | **缺失** | 3 章补节 |
| KV cache 与推理 | 无 | **缺失** | 3 章补节 |
| 多模态输入 | 4 次提及 | 不足 | 1 章补节 |
| logprobs / 置信度 | 只在概率意义上讲 | 不足 | 2 章补节 |
| 结构化输出五种做法 | 手写 | 不足 | 4 章换真实 SDK；9.7 与 LangChain 对照 |
| 其余（窗口/角色/finish_reason/usage/温度/流式） | 已覆盖 | 覆盖 | — |

### 4.2 Agent 层

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| 并行工具调用 | 提及 1 次 | 不足 | 6 章补节 |
| 工具 schema / 循环 / 终止 / 失控 | 已覆盖 | 覆盖 | 6–8 章（代码换真实 SDK） |
| 编排范式 / 反思 / 状态 / 持久化 | 已覆盖 | 覆盖 | 23–26 章（从原位置后移） |
| MCP | 手写 JSON-RPC | 不足 | 27 章换 `mcp` SDK |
| Skill 三级加载 | 已覆盖 | 覆盖 | 27 章 |
| handoff / subagent | 有概念 | 不足 | 34、39 章 |

### 4.3 RAG 层

| 概念 | 判定 | 去向 |
|---|---|---|
| 文档解析（PDF/表格） | **缺失** | 14 章补节 |
| 切块五法 | 覆盖 | 16 章（换真实切块器） |
| token 切块 / 语义切块 / 表格切分 | **缺失** | 16 章 |
| 嵌入是什么 / 归一化 / 距离度量 | **缺失** | 15 章 |
| 相似度读数 / 维度与成本 / 截断 / 查询侧指令 / 批量嵌入 | **缺失或不足** | 15 章 |
| 向量库职责 / HNSW / IVF-PQ / 距离匹配 / 持久化 / 分片 / 量化 / 选型 | **缺失** | 17 章 |
| payload 过滤 / 预过滤 / 多租户 / upsert | 不足 | 17 章 |
| 混合检索 / RRF / 重排 / 改写 | 覆盖 | 18 章（换真实库） |
| MMR / MRR / nDCG | **缺失** | 18 章 + 44 章 |
| 上下文装配 / 长期记忆 / 治理 | 覆盖 | 19–21 章（换真实 tokenizer / qdrant） |

### 4.4 约束、度量、工程

| 概念 | 判定 | 去向 |
|---|---|---|
| 沙箱 / 网络出口 / 护栏 / PII / 注入 / 审批 / 对外形态 / 交付 | 覆盖 | 28–33 章 |
| 灰度与回滚 | 覆盖 | 33 章 |
| 密钥与配置 | 不足 | 5 章（Settings）+ 33 章 |
| span / OTel / 落盘 / 采样 | 不足 | 43 章（换真 SDK） |
| LangFuse | **缺失** | 43 章 |
| RAG 评测四指标 / 评测集 / RAGAS | **缺失或不足** | 44 章 |
| Agent 评测四层 / 裁判 kappa / 多轮 HITL | 覆盖 | 45 章（补框架示例） |
| 统计区间 / 门禁 / 成本 / 延迟 / 复盘 | 覆盖 | 46–47 章 |
| **pydantic / Settings** | **缺失** | **5 章** |
| 日志 / 测试 / 依赖 / 并发 | 覆盖 | 分散，不新增 |

---

## 五、代码实例清单（按新章号）

| 章 | 现在 | 补什么 | 库 |
|---|---|---|---|
| 1 | 手造响应 | 真实响应对象 + 多模态内容块 | `openai`（回放服务器） |
| 2 | 手写分布 | 三档温度真实采样 + logprobs | `openai`（回放） |
| 3 | `len//2` | 分词、成本、KV cache 影响 | `tiktoken` |
| 4 | 正则抽 JSON | 五种做法真跑 + pydantic 校验 | `openai`、`pydantic` |
| 5 | 无 | pydantic 全量 | `pydantic`、`pydantic-settings` |
| 6 | 手写 tool_calls | `tools=` 往返 + 并行调用 | `openai`（回放） |
| 9–12 | 无 | LangChain 四章示例（见 3.1） | `langchain` |
| 13 | 手写路由 | embedding 路由 + 阈值 | `sentence-transformers` |
| 14 | 字符 2-gram | 端到端 pipeline（手写版） | `bge`+`qdrant`+`tiktoken` |
| 15 | 无 | 向量化实脸 | `sentence-transformers` |
| 16 | 手写切法 | 递归/标题/token/语义切块 | `langchain-text-splitters`、`tiktoken` |
| 17 | 手写索引类 | qdrant Flat/IVF/HNSW、过滤、持久化、量化 | `qdrant-client`、`faiss` |
| 18 | 手写 BM25/RRF | 真实 BM25+向量+RRF+CrossEncoder+MMR | `rank_bm25`、`sentence-transformers`、`qdrant` |
| 19 | 字符计 token | `tiktoken` 预算 | `tiktoken` |
| 20–21 | 手写记忆/治理 | qdrant 三层记忆 + payload 版本过滤 | `qdrant` |
| 22 | 无 | LangChain 的 RAG（与 14 章对照） | `langchain`、`qdrant` |
| 23–27 | 手写 | 保留手写 + 27 章换 `mcp` SDK | `mcp` |
| 28–33 | 手写 | 保留；25 章补中间件、31 章补 `interrupt()` | `langchain`、`langgraph` |
| 34 | 旧 24 章 | 拆分判据 + 协作形态 | 标准库 |
| 35 | 无 | A2A 最小往返 | `a2a-sdk` |
| 36 | 无 | 手写 supervisor/handoff | 标准库 |
| 37–39 | 无 | LangGraph 三章 | `langgraph` |
| 40–41 | 无 | LlamaIndex 两章 | `llama-index` |
| 42 | 无 | 各框架最小例子 | `pydantic-ai`、`openai-agents`、平台说明 |
| 43 | 手写 span | OTel 真 span + LangFuse 上报 | `opentelemetry-sdk`、`langfuse` |
| 44 | 字面重合 | 真实嵌入 + RAGAS 对照 + 评测集 | `ragas`、`sentence-transformers` |
| 45 | 手写裁判 | 评测框架跑同一批用例 | 见 42 章 |
| 48–52 | 未写 | 契约与替换实验 | 标准库 |

---

## 六、执行批次

| 批 | 章 | 验收 |
|---|---|---|
| 0 | 全库重排为 53 章 | 引用扫描 0 错、所有脚本跑通 |
| 1 | 15 向量化、16 切块、17 向量数据库 | 三章各 1–2 个真实库示例 |
| 2 | 14、18、22 | 端到端 pipeline、混合重排、LangChain RAG |
| 3 | 9–12 LangChain 四章 | 四章各自可跑，含一个完整 agent |
| 4 | 43、44、45 | Docker 起 LangFuse；RAGAS 跑通；评测框架对照 |
| 5 | 34–36 多智能体 | A2A 往返 + 两种手写编排 |
| 6 | 37–39 LangGraph | 三个图（含中断恢复与多智能体） |
| 7 | 40–42 LlamaIndex 与其他 | 每框架最小可跑 |
| 8 | 1–6、13、19–21、23–33 补齐 | 每章至少一处真实库 |
| 9 | 48–52 副线 | 替换实验通过 |

**三条硬规则**：① 一个示例最多跑 3 次，仍失败写"环境限制"说明；② 代用品必须标注并降为对照；③ 框架章必须按第三节列出的节写，不得合并压缩。

---

## 七、待确认

1. 第三节的框架章内容清单是否够细（尤其 LangChain 四章、LangGraph 三章）。
2. 第 1、2、4、6 章要用 `openai` SDK 但没有 key：是否允许"本地 OpenAI 兼容回放服务器"（回放真实响应体，标注为模拟传输）。
3. 第 5 章 pydantic 放在卷 1 末尾是否合适（它是第 4、6、9–12 章的共同底座）。
