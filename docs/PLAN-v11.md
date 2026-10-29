# 改造方案 v11：RAG 章以 RAG 为主、LangChain 为副线

> 取代 v10。本版只改一件事，但改的是定位：
> **RAG 九章（13–21）的主体是 RAG 本身；LangChain 是这些章的副线，同时承担全部代码示例。副线要讲全 API，但不能反客为主。**
>
> 其余结构沿用 v10：LangChain 的 agent 侧四章（9–12）在 RAG 之前，作为平滑过渡；进阶与工程化在 RAG 之后；多智能体、LangGraph 更后。

> **2026-10-30 增补（本文以下按 53 章记录，未回改）**：新增卷 11「形态与结构」（47–50），副线后移为卷 12（51–56），总章数 53 → 57。改动的依据见 `outline/52-设计决定.md` 第 31–33 条，四章的节级计划见 `outline/44-形态与结构章节计划.md`。

---

## 一、定位与写法（本版核心）

### 1.1 一章的固定结构

```
第 N 章 · RAG 的某个环节
  主线（约 70%）：是什么 → 不做会怎么坏 → 怎么选 → 怎么验收
  副线（约 30%）：LangChain 实现
      N.k LangChain 的对应组件（参数逐个讲）
      N.k+1 最小可跑示例
      N.k+2 与主线概念的逐条映射（哪个 API 对应哪个概念）
  边界：这个环节不该做什么
```

### 1.2 三条硬约束

| # | 约束 | 判定方法 |
|---|---|---|
| 1 | **RAG 是主，LangChain 是副** | 去掉所有 LangChain 代码段落，本章的论证仍然完整；反之不成立 |
| 2 | **副线必须讲全** | 每章列出"必讲的 API 清单"（见第四节），一个不漏 |
| 3 | **副线不抢跑** | LangChain 只讲本章环节用得到的部分；agent 侧的 API 留在 9–12 章 |

### 1.3 为什么这样切

- 读者学 RAG，不是学 LangChain 的目录；把 LangChain 拆成"每个环节的现成实现"，学完 RAG 自然学会 LangChain 的 RAG 部分。
- 同时保证"框架不压缩"：每章的副线都有独立小节，API 逐个参数讲，不写成"详见官方文档"。
- 与 9–12 章（agent 侧）形成两段：agent 侧讲"框架怎么搭循环"，RAG 侧讲"框架怎么装检索"，中间用 12.6 过渡。

---

## 二、全书结构（53 章，0–52）

| 卷 | 名称 | 章 | 说明 |
|---|---|---|---|
| 0 | 起点 | 0 | agent 是什么 |
| 1 | 一次调用 | 1–5 | 四字段 / 编与忘 / token 成本 / 结构化输出 / pydantic |
| 2 | 最小 agent | 6–8 | 工具 / 循环 / 终止与失控 |
| 3 | LangChain（agent 侧） | 9–12 | 基础 / 组合 / 工具 / Agent + 过渡节 |
| 4 | **RAG（LangChain 为副线）** | 13–21 | 分流 / 四环节 / 向量化 / 切块 / 向量库 / 检索质量 / 装配 / 记忆 / 治理 |
| 5 | agent 进阶 | 22–26 | 范式 / 反思 / 状态 / 持久化 / MCP·Skill |
| 6 | agent 工程化 | 27–32 | 沙箱 / 护栏 / 注入 / 审批 / 对外形态 / 交付 |
| 7 | 多智能体 | 33–35 | 拆分与协作 / A2A / 手写编排 |
| 8 | LangGraph | 36–38 | 图与状态 / 持久化与流式 / 多智能体编排 |
| 9 | 其他框架 | 39–41 | LlamaIndex 两章 / 其他技术栈与平台 |
| 10 | 度量与复盘 | 42–46 | 计量（OTel+LangFuse）/ RAG 评测（RAGAS）/ Agent 评测 / 门禁 / 成本延迟 |
| 11 | 组件封装（副线） | 47–52 | 契约与替换实验 + 组合（拓扑） |

知识点：A9 + B21 + C12 + D15 + E14 + F18 + H13 + G5 = 108 条（含 G6 LLM Wiki）。早期草案的 C13/C14/D16/H14 不单列——嵌入原理并入 C7、向量库运维并入 C6，其余并入既有章。

---

## 三、RAG 九章：主线 / 副线逐节

### 第 13 章 · 分流

| 类型 | 节 |
|---|---|
| 主线 | 13.1 三类请求与判据；13.2 误分流的两侧代价；13.3 规则路由；13.4 向量路由；13.5 兜底率与归因 |
| 副线 | 13.6 `HuggingFaceEmbeddings` 做意图质心 + 阈值（本章唯一用到 LangChain 的地方） |

> 路由发生在检索之前，LangChain 没有对应抽象；这一章的主线占比最高。

### 第 14 章 · RAG 的四个环节

| 类型 | 节 |
|---|---|
| 主线 | 14.1 四段为什么分开；14.2 检索的两类失败；14.3 拼装的三种坏法；14.4 生成的约束写在拼装里；14.5 引用三个作用与两个率；14.6 一次坏回答的四步归因 |
| 副线 | 14.7 `Document`/`TextSplitter`/`VectorStore`/`Retriever` 的接口全貌；14.8 `create_retrieval_chain` 式装配；14.9 端到端 pipeline 示例（含引用校验） |
| 映射 | 14.10 四环节 ↔ LangChain 组件逐条对照表 |

### 第 15 章 · 向量化

| 类型 | 节 |
|---|---|
| 主线 | 15.1 嵌入是什么；15.2 归一化与距离；15.3 相似度读数与阈值；15.4 维度与成本；15.5 截断；15.6 稀疏 vs 稠密；15.7 批量与缓存 |
| 副线 | 15.8 `HuggingFaceEmbeddings` 参数与批量；15.9 `embed_query` vs `embed_documents`；15.10 `distance_strategy`；15.11 相似度矩阵示例 |
| 映射 | 15.12 三条主线结论 → 三个 API 参数 |

### 第 16 章 · 切块

| 类型 | 节 |
|---|---|
| 主线 | 16.1 块是检索最小单位；16.2 切错三后果；16.3 五种切法；16.4 块大小怎么定；16.5 父子块；16.6 表格与代码块 |
| 副线 | 16.7 `CharacterTextSplitter`；16.8 `RecursiveCharacterTextSplitter`；16.9 `MarkdownHeaderTextSplitter`；16.10 `from_tiktoken_encoder`；16.11 `SemanticChunker`；16.12 `ParentDocumentRetriever` |
| 映射 | 16.13 五种切法 → 五个类（含参数） |

### 第 17 章 · 向量数据库

| 类型 | 节 |
|---|---|
| 主线 | 17.1 向量库职责；17.2 三种索引与参数；17.3 距离与索引匹配；17.4 过滤与预过滤；17.5 多租户；17.6 写入语义；17.7 持久化/分片/量化；17.8 选型 |
| 副线 | 17.9 `QdrantVectorStore` 建库与写入；17.10 `filter` 语法与 payload；17.11 三种索引配置对照；17.12 `Chroma`/`FAISS`/`PGVector` 接入差异 |
| 映射 | 17.13 运维问题 → LangChain 接口 |

### 第 18 章 · 检索质量

| 类型 | 节 |
|---|---|
| 主线 | 18.1 稠密与稀疏互补；18.2 RRF；18.3 重排；18.4 改写；18.5 MMR；18.6 指标 recall@k/MRR/nDCG；18.7 何时不该加 |
| 副线 | 18.8 `EnsembleRetriever`+`BM25Retriever`；18.9 `ContextualCompressionRetriever`+`CrossEncoderReranker`；18.10 `MultiQueryRetriever`；18.11 `search_type="mmr"` 与 λ |
| 映射 | 18.12 手段 → 类 → 代价 |

### 第 19 章 · 上下文装配

| 类型 | 节 |
|---|---|
| 主线 | 19.1 四槽位；19.2 预算与抢占；19.3 拼接顺序与编号；19.4 压缩；19.5 装配可观测 |
| 副线 | 19.6 `ChatPromptTemplate` + 引用编号；19.7 `trim_messages` 与 token 计数；19.8 `LLMChainExtractor` 压缩 |
| 映射 | 19.9 预算表 ↔ 每段 token 的 API |

### 第 20 章 · 长期记忆

| 类型 | 节 |
|---|---|
| 主线 | 20.1 三层记忆；20.2 写入什么；20.3 召回与时间衰减；20.4 软删与遗忘；20.5 记忆污染 |
| 副线 | 20.6 `VectorStore` 存记忆与元数据；20.7 租户/时间过滤；20.8 `delete` 幂等 |
| 映射 | 20.9 三层记忆 → 三个元数据字段 |

### 第 21 章 · 知识治理

| 类型 | 节 |
|---|---|
| 主线 | 21.1 改/删/版本共存；21.2 增量更新；21.3 检索过滤失效；21.4 缓存键与索引版本；21.5 矛盾检测与可溯源 |
| 副线 | 21.6 `Document.metadata` 带版本与来源；21.7 按 doc_id 删旧插新；21.8 过滤写进查询；21.9 版本重载 |
| 映射 | 21.10 治理动作 → 一次调用 |

---

## 四、副线 API 覆盖清单（"讲全"的判据）

| 章 | 必须出现的 API/类 | 必须出现的参数 |
|---|---|---|
| 13 | `HuggingFaceEmbeddings` | `model_name`、`encode_kwargs` |
| 14 | `Document`、`TextSplitter`、`VectorStore`、`Retriever`、`create_retrieval_chain` | `invoke` 的输入输出键 |
| 15 | `HuggingFaceEmbeddings` | `model_name`、`encode_kwargs={"normalize_embeddings": True}`、`embed_query`/`embed_documents` |
| 16 | 五个 Splitter + `ParentDocumentRetriever` | `chunk_size`、`chunk_overlap`、`separators`、`headers_to_split_on`、`encoding_name`、`breakpoint_threshold_type`、`child_splitter`/`parent_splitter` |
| 17 | `QdrantVectorStore`、`Chroma`、`FAISS`、`PGVector` | `collection_name`、`distance`、`hnsw_config`、`filter`、`ids`、`delete`、`persist` |
| 18 | `EnsembleRetriever`、`BM25Retriever`、`ContextualCompressionRetriever`、`CrossEncoderReranker`、`MultiQueryRetriever` | `weights`、`k`、`fetch_k`、`lambda_mult`、`search_type` |
| 19 | `ChatPromptTemplate`、`trim_messages`、`LLMChainExtractor` | `max_tokens`、`strategy`、`token_counter`、`include_system` |
| 20 | `VectorStore`、`Document.metadata` | 租户/时间字段、`filter`、`delete` |
| 21 | `Document.metadata`、`VectorStore.delete`、`filter` | `version`、`source`、`active`、`doc_id` |

---

## 五、LangChain agent 侧（9–12）：逐节内容

> 按本机安装的 **LangChain 1.4.7** 实际接口核对过；正文锁定该版本，章首标注版本号。

**第 9 章 · 基础**

| 节 | 内容 | API |
|---|---|---|
| 9.1 | 包结构与版本边界 | `langchain-core`/`langchain`/`langchain-openai`/`langchain-community`；版本不匹配的典型报错 |
| 9.2 | 模型接入 | `init_chat_model(model, model_provider, configurable_fields, config_prefix, **kwargs)`；OpenAI 兼容端点 `base_url` |
| 9.3 | 四种消息 | `SystemMessage`/`HumanMessage`/`AIMessage`/`ToolMessage`；`content` vs `content_blocks` |
| 9.4 | 三类元信息 | `additional_kwargs`/`response_metadata`/`usage_metadata`，对上第 1 章字段 |
| 9.5 | 消息裁剪 | `trim_messages(max_tokens, strategy, token_counter, include_system)` |
| 9.6 | 流式 | `.stream()`/`.astream()`/`.astream_events()`；与第 31 章 SSE 对应 |
| 9.7 | 结构化输出 | `with_structured_output(schema, method=...)` 三策略，与第 4 章五种做法对照 |

**第 10 章 · 组合**

| 节 | 内容 | API |
|---|---|---|
| 10.1 | Runnable 协议 | `invoke`/`batch`/`stream`/`astream_events` 与输入输出契约 |
| 10.2 | 七个组合子 | `\|`、`RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableBranch`、`with_fallbacks`、`with_retry` |
| 10.3 | 模板 | `ChatPromptTemplate`、`MessagesPlaceholder`、`FewShotChatMessagePromptTemplate` |
| 10.4 | 解析器 | `StrOutputParser`/`JsonOutputParser`/`PydanticOutputParser`/`CommaSeparatedListOutputParser` |
| 10.5 | 自愈 | `OutputFixingParser`/`RetryOutputParser`，对上第 4 章"校验失败回灌" |
| 10.6 | 调试 | `astream_events` 事件树（事件名与父子关系） |

**第 11 章 · 工具**

| 节 | 内容 | API |
|---|---|---|
| 11.1 | 三种定义 | `@tool`、`BaseTool` 子类、`StructuredTool`；`args_schema`（pydantic） |
| 11.2 | 绑定与调用 | `bind_tools`、`tool_choice`、并行 `tool_calls`；与第 6 章手写往返对照 |
| 11.3 | 注入 | `InjectedState`、`InjectedStore`、`ToolRuntime` |
| 11.4 | 错误与重试 | `ToolRetryMiddleware`、`ToolErrorMiddleware` |
| 11.5 | 工具收窄 | `LLMToolSelectorMiddleware`、`ToolCallLimitMiddleware`；与第 28 章护栏对照 |
| 11.6 | 工具模拟 | `LLMToolEmulator`（无副作用地跑评测） |

**第 12 章 · Agent**

| 节 | 内容 | API |
|---|---|---|
| 12.1 | 全参数 | `create_agent` 的 15 个参数：`model`/`tools`/`system_prompt`/`middleware`/`response_format`/`state_schema`/`context_schema`/`checkpointer`/`store`/`interrupt_before`/`interrupt_after`/`debug`/`name`/`cache` |
| 12.2 | 中间件协议 | `AgentMiddleware`；钩子 `before_agent`/`after_agent`/`before_model`/`after_model`/`wrap_model_call`/`wrap_tool_call`/`dynamic_prompt`/`hook_config`；洋葱顺序与短路 |
| 12.3 | 内置中间件（四组） | 预算与重试：`ModelCallLimitMiddleware`/`ModelRetryMiddleware`/`ModelFallbackMiddleware`/`ToolCallLimitMiddleware`；上下文：`SummarizationMiddleware`/`ContextEditingMiddleware`/`TodoListMiddleware`；安全与人工：`PIIMiddleware`/`HumanInTheLoopMiddleware`；执行环境：`ShellToolMiddleware`/`FilesystemFileSearchMiddleware`/`DockerExecutionPolicy`/`CodexSandboxExecutionPolicy`/`HostExecutionPolicy` |
| 12.4 | 状态与持久化 | `state_schema`/`context_schema`/`checkpointer`/`store`；与第 22、24 章对照 |
| 12.5 | 中断 | `interrupt_before`/`interrupt_after` 与 `HumanInTheLoopMiddleware` 的分工 |
| 12.6 | 与手写循环逐项对照 | 终止、状态、预算、审批、工具执行各落在哪（对照第 7 章） |
| 12.7 | 过渡到 RAG | 演示"agent 答不出自家文档"，预告第 13 章 |

**覆盖原则**：只讲 agent 侧（检索/切块/向量库不进）；每个 API 都要真跑，不写"详见文档"；与主线逐条对照（11↔6、12↔7、9.7↔4、9.5↔3、10.5↔4.6）。

---

## 六、其余卷（摘要）

| 卷 | 章 | 要点 |
|---|---|---|
| 5 进阶 | 22–26 | 范式 / 反思 / 状态 / 持久化 / MCP·Skill（26 换 `mcp` SDK） |
| 6 工程化 | 27–32 | 沙箱 / 护栏 / 注入 / 审批 / 对外形态 / 交付（28 补中间件、30 补 `interrupt()`） |
| 7 多智能体 | 33–35 | 拆分判据 / A2A（`a2a-sdk`）/ 手写 supervisor-handoff |
| 8 LangGraph | 36–38 | 图与状态 / 持久化与流式 / 多智能体编排 |
| 9 其他 | 39–41 | LlamaIndex 两章 / Deep Agents、pydantic-ai、Agents SDK、AutoGen、CrewAI、平台 |
| 10 度量 | 42–46 | 计量（OTel+LangFuse）/ RAG 评测（评测集+RAGAS）/ Agent 评测 / 门禁 / 成本延迟 |
| 11 封装 | 47–52 | 契约与替换实验 + 组合（副线） |

---

## 七、概念清查去向（节选，按 v11 章号）

| 概念 | 判定 | 去向 |
|---|---|---|
| token/分词器、chat template、KV cache | 不足/缺失 | 3 章 |
| 多模态、logprobs | 不足 | 1 章 / 2 章 |
| 结构化输出五法 | 不足 | 4 章（+9.7） |
| 并行工具调用 | 不足 | 6 章 |
| 工具注入/收窄 | 缺失 | 11 章 |
| MCP（换 SDK） | 不足 | 26 章 |
| 文档解析（PDF/表格） | 缺失 | 14 章（主线） |
| 切块五法 + token/语义/父子/表格 | 覆盖但代码假 | 16 章（副线实现） |
| 嵌入原理/距离/读数/维度/截断/查询侧/批量 | 缺失或不足 | 15 章 |
| 向量库职责/HNSW/IVF-PQ/过滤/多租户/持久化/选型 | 缺失 | 17 章 |
| 混合/RRF/重排/改写/MMR/MRR/nDCG | 部分缺失 | 18 章 |
| 装配/记忆/治理 | 覆盖但代码假 | 19–21 章 |
| 沙箱/护栏/注入/审批/交付 | 覆盖 | 27–32 章 |
| span/OTel/LangFuse | 不足/缺失 | 42 章 |
| 评测集/RAGAS | 缺失 | 43 章 |
| Agent 评测框架 | 缺失 | 44 章 |
| 统计/门禁/成本 | 覆盖 | 45–46 章 |
| **pydantic / Settings** | 缺失 | **5 章** |

---

## 八、代码实例与批次

RAG 卷代码全部在副线节里，用 LangChain；其余卷的代码清单与 v10 相同（1–6 用 `openai` 回放 + `tiktoken` + `pydantic`；22–32 手写为主，26/28/30 接框架；33–35 `a2a-sdk`；36–41 各框架；42–46 观测与评测）。

| 批 | 章 | 验收 |
|---|---|---|
| 0 | 全库重排为 53 章 | 引用扫描 0 错、脚本跑通 |
| 1 | 9–12 | LangChain agent 侧四章 + 过渡节可跑 |
| 2 | 13–15 | 分流、端到端、向量化（含副线实现） |
| 3 | 16–18 | 切块、向量库、检索质量（副线 API 覆盖清单逐项打勾） |
| 4 | 19–21 | 装配、记忆、治理 |
| 5 | 42–44 | LangFuse + RAGAS + 评测框架 |
| 6 | 33–35 | A2A + 手写编排 |
| 7 | 36–38 | LangGraph 三章 |
| 8 | 39–41 | LlamaIndex 与其他栈 |
| 9 | 1–6、22–32 补齐 | 每章至少一处真库 |
| 10 | 47–52 | 副线封装与组合 |

**验收判据（RAG 卷）**：① 去掉副线节，本章论证仍完整；② 副线 API 清单逐项出现；③ 每章至少一个可跑示例；④ 示例最多试 3 次。

---

## 九、待确认

1. RAG 章"主线 70% / 副线 30%"的比例是否合适？
2. 第 13 章"分流"只保留一小节 LangChain（`HuggingFaceEmbeddings`），是否接受？
3. 第 1、2、4、6 章无 key，是否允许本地 OpenAI 兼容回放服务器？
