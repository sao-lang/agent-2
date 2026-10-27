> **本文件已被 [PLAN-v8.md](./PLAN-v8.md) 取代。** v8 按「LangChain 四章、基础先行、进阶后置、框架内容列到节」重做，结构与节次以 v8 为准。

# 改造方案 v7：概念补齐、技术栈归位、全书重排

> 触发：① 主线章节没有真实技术栈代码；② RAG 缺"向量化 / 向量数据库"两块地基；③ 框架章的位置不对（LangChain 与 LangGraph 连着出现、LlamaIndex 与 RAGAS 各自孤立）。
> 本文件是**方案**，不改正文。确认后按第五节分批执行。
> 配套清查：`docs/AUDIT-CODE-GAPS.md`（代码缺口）、`docs/AUDIT-CONCEPTS.md`（RAG 概念缺口）、`docs/audit_concepts.py`（全书概念扫描）。

---

## 一、五条修改原则（来自本轮确认）

| # | 原则 | 落地方式 |
|---|---|---|
| 1 | **基本概念先讲清，再给代码** | 每个概念三段：是什么 → 不做会怎么坏 → 最小可跑示例。概念不靠代码"带出来" |
| 2 | **技术栈跟着主题走，不另设独立框架卷** | LangChain 讲完 agent 基础就出现；OTel/LangFuse 直接并进"计量与可观测"；RAGAS 直接并进"RAG 评测" |
| 3 | **LangChain 与 LangGraph 不同框出现** | 第 14 章只讲 LangChain 搭 agent；LangGraph 放到全书最后（第 38 章）统一讲，含多智能体编排 |
| 4 | **LlamaIndex 的 RAG 做法后置统一讲** | 第 39 章：同一批文档用 LlamaIndex 重做一遍，与第 16–20 章对照 |
| 5 | **其余技术栈与平台集中一章** | 第 40 章：Deep Agents、pydantic-ai、OpenAI Agents SDK、AutoGen、CrewAI、Coze/Dify |

补充一条**允许/不允许**的边界（防止又跑偏）：

- 主线章允许用**部件库**：`tiktoken`、`pydantic`、`sentence-transformers`、`qdrant`/`faiss`、`rank_bm25`+`jieba`、`mcp`、`a2a-sdk`、`opentelemetry-sdk`。
- 主线章不允许用**框架**：LangChain/LangGraph/LlamaIndex/pydantic-ai 的编排层、RAGAS、LangFuse、Agent 评测框架——它们只出现在第 14、30、31、32、38、39、40 章。

---

## 二、全书概念清查清单

判定口径：**覆盖**＝有定义、有失效分析、有示例；**不足**＝提到但没讲透或缺示例；**缺失**＝没有。

### 2.1 模型层

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| token 与分词器（BPE、词表） | 第 3 章有估算与 usage 校准，无分词器原理 | 不足 | 第 3 章补"分词器"一节 + `tiktoken` 实测 |
| chat template 与特殊 token | 无 | **缺失** | 第 1 或 3 章补节（拼接错模板是线上常见事故） |
| 上下文窗口 | 第 3 章 | 覆盖 | — |
| 消息角色与层级 | 第 1 章 | 覆盖 | — |
| `finish_reason` | 第 1 章 | 覆盖 | — |
| usage 与计费 | 第 3 章 | 覆盖 | — |
| 温度 / top_p / 采样 | 第 2 章 | 覆盖 | — |
| logprobs 与置信度 | 只在"概率"意义上讲 | 不足 | 第 2 章补"怎么拿到模型自己的置信度" |
| 流式与 SSE | 第 25 章 | 覆盖 | — |
| function calling | 第 5 章（概念） | 不足（代码手写） | 第 5 章换真实 `tools=` 往返 |
| 结构化输出 | 第 4 章（手写） | 不足 | 第 4 章换 `response_format`/`json_schema`/`with_structured_output` |
| max_tokens 与 stop | 第 1、3 章 | 覆盖 | — |
| 多模态输入 | 提到 4 次 | 不足 | 第 1 章补一节（图片输入与 token 计费） |
| KV cache 与推理 | 无 | **缺失** | 第 3 章补"为什么长上下文贵/快" |
| 模型选型与能力边界 | 第 2、13 章 | 覆盖 | — |

### 2.2 Agent 层

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| 工具 schema | 第 5 章 | 覆盖 | 第 5 章补真实 schema |
| 并行工具调用 | 1 次提及 | 不足 | 第 6 章补"一次返回多个 tool_calls" |
| 工具错误与重试 | 第 9、25 章 | 覆盖 | — |
| 循环与终止 | 第 6 章 | 覆盖 | — |
| 四种失控 | 第 7 章 | 覆盖 | — |
| 编排范式 | 第 8 章 | 覆盖 | — |
| handoff 与 subagent | 第 24 章 | 覆盖 | — |
| 反思与裁判 | 第 9 章 | 覆盖 | — |
| 状态与 reducer | 第 10 章 | 覆盖 | — |
| 持久化与幂等 | 第 11 章 | 覆盖 | — |
| MCP | 第 12 章（手写 JSON-RPC） | 不足 | 换 `mcp` SDK（`MCPServer`） |
| Skill 与三级加载 | 第 12 章 | 覆盖 | — |
| 上下文裁剪 | 第 7、17 章 | 覆盖 | — |

### 2.3 RAG 层（本轮重点）

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| 文档解析（PDF/表格/页眉页脚） | 只有"解析出结构"一句 | **缺失** | 第 16 章补节（`unstructured`/`markdown`） |
| 切块策略（定长/标题/句子/父子/问题） | 第 15 章 | 覆盖 | 移到新的"切块"专章 |
| token 切块 | 无 | **缺失** | 切块专章 |
| 语义切块 | 无 | **缺失** | 切块专章 |
| 表格 / 代码块切分 | 只提"标题数 ≤ 1" | 不足 | 切块专章 |
| **嵌入是什么**（向量空间语义） | 一句"语义压成中心点" | **缺失** | **新增"向量化"章** |
| **归一化与距离度量**（cosine/dot/L2） | 只在代码里有 `cosine()` | **缺失** | 向量化章 |
| **相似度数值怎么读**（0.62 高低、阈值） | 只讲缓存阈值 | 不足 | 向量化章 |
| **维度与成本**（512/768/1536） | 示意表，无实测 | 不足 | 向量化章（bge-512 实测） |
| **截断**（`max_seq_length`） | 无 | **缺失** | 向量化章 |
| **查询侧 vs 文档侧** | 一句 | 不足 | 向量化章（bge query instruction） |
| 稀疏 vs 稠密 | 第 16 章 | 覆盖 | — |
| 批量嵌入与服务 | 无 | **缺失** | 向量化章 |
| **向量库的职责** | 只有名词 | **缺失** | **新增"向量数据库"章** |
| **HNSW**（M/efConstruction/efSearch） | 出现 1 次 | **缺失** | 向量数据库章 |
| **IVF / PQ** | 用"倒排分桶"近似 | **缺失** | 向量数据库章 |
| **距离与索引匹配** | 无 | **缺失** | 向量数据库章 |
| **payload 过滤 / 预过滤 vs 后过滤** | 一句"过滤必须在检索前" | 不足 | 向量数据库章（qdrant 实测） |
| **多租户隔离** | 记忆章讲过，库层面无 | 不足 | 向量数据库章 |
| **upsert / 软删 / 重建** | 文档章讲过，库层面无 | 不足 | 向量数据库章 |
| **持久化 / 分片 / 副本 / 量化** | 无 | **缺失** | 向量数据库章 |
| **选型**（Qdrant/Milvus/pgvector/FAISS/Chroma） | 无 | **缺失** | 向量数据库章 |
| 混合检索与 RRF | 第 16 章 | 覆盖 | 换真实库重写示例 |
| 重排（CrossEncoder） | 第 16 章 | 覆盖 | 换真实 CrossEncoder |
| 查询改写 | 第 16 章 | 覆盖 | — |
| **MMR 多样性** | 2 次提及 | 不足 | 检索质量章 |
| **MRR / nDCG** | 无 | **缺失** | 检索质量章 + 评测章 |
| 上下文装配（四槽位） | 第 17 章 | 覆盖 | 换 `tiktoken` 计数 |
| 长期记忆三层 | 第 18 章 | 覆盖 | 换 qdrant 实现 |
| 知识治理与版本 | 第 19 章 | 覆盖 | 换向量库 payload 过滤 |
| 引用校验 | 第 14 章 | 覆盖 | — |

### 2.4 约束层

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| 沙箱四条边界 | 第 20 章 | 覆盖 | — |
| 网络出口与 SSRF | 第 20 章 | 覆盖 | — |
| 护栏 / 白名单 / 两个率 | 第 21 章 | 覆盖 | 补 LangChain 中间件示例（技术栈小节） |
| PII | 第 21 章 | 覆盖 | — |
| 注入（直接/间接） | 第 21、22 章 | 覆盖 | — |
| 审批与中断恢复 | 第 23 章 | 覆盖 | 补 LangGraph `interrupt()` 示例 |
| 多智能体 | 只有第 24 章 | 不足 | **独立成卷**（35–37） |
| 对外形态（同步/异步/流式） | 第 25 章 | 覆盖 | — |
| 交付四件套 / 容器 | 第 26 章 | 覆盖 | — |
| 密钥与配置 | 分散 | 不足 | pydantic-chapter + 第 26 章 |
| 灰度与回滚 | 多处提及 | 覆盖 | — |

### 2.5 度量层

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| 计量字段 / span 树 | 第 27 章（手写） | 不足 | 换 `opentelemetry-sdk` 真 span |
| OTel 约定 | 只有字段映射表 | 不足 | 并入"计量与可观测"章，真导出 |
| 可追踪平台（LangFuse） | 无（原计划独立章） | **缺失** | **并入第 30 章**（按新规则） |
| 落盘与采样 | 第 27 章 | 覆盖 | — |
| RAG 评测四指标 | 第 28 章（字面重合） | 不足 | 换真实嵌入 + **RAGAS 并入本章** |
| 评测集怎么建 | 无 | **缺失** | **并入第 31 章** |
| 检索指标 recall/precision | 第 28 章 | 覆盖 | 补 MRR/nDCG |
| Agent 评测四层 | 第 29 章 | 覆盖 | 补评测框架示例（并入本章） |
| 裁判可信（kappa） | 第 29 章 | 覆盖 | — |
| 多轮与 HITL | 第 29 章 | 覆盖 | — |
| 统计与区间 / 门禁 | 第 30 章 | 覆盖 | — |
| 成本 / 延迟 / 复盘 | 第 31 章 | 覆盖 | 接 LangFuse 真实用量 |

### 2.6 工程基础

| 概念 | 现状 | 判定 | 去向 |
|---|---|---|---|
| **pydantic**（模型、校验、schema、Settings） | 全书 1 次 | **缺失** | **新增第 5 章** |
| 配置管理 | 1 次 | 不足 | 第 5 章（pydantic-settings）+ 第 26 章 |
| 日志与错误分类 | 第 0、26 章 | 覆盖 | — |
| 测试与夹具 | 第 20、21 章 | 覆盖 | — |
| 依赖与版本 | 多处 | 覆盖 | — |
| 并发与线程 | 第 25、26 章 | 覆盖 | — |

---

## 三、新结构（46 章，0–45）

| 卷 | 名称 | 章 | 内容要点 |
|---|---|---|---|
| 0 | 起点 | 0 | 不变 |
| 1 | 一次调用 | 1–5 | 1 四字段 / 2 编与忘 / 3 token·成本·窗口 / 4 结构化输出 / **5 pydantic** |
| 2 | 从调用到循环 | 6–14 | 6 工具 / 7 循环 / 8 失控 / 9 编排 / 10 反思 / 11 状态 / 12 持久化 / 13 MCP·Skill / **14 LangChain 搭 agent** |
| 3 | 从循环到系统 | 15–23 | 15 分流 / 16 RAG 四环节（**LangChain 端到端**）/ **17 向量化** / **18 切块** / **19 向量数据库** / 20 检索质量 / 21 上下文装配 / 22 长期记忆 / 23 知识治理 |
| 4 | 从系统到可上线 | 24–29 | 24 沙箱 / 25 护栏 / 26 注入 / 27 审批 / 28 对外形态 / 29 交付 |
| 5 | 从上线到可证明 | 30–34 | 30 计量与可观测（**OTel + LangFuse**）/ 31 RAG 评测（**评测集 + RAGAS**）/ 32 Agent 评测（**评测框架**）/ 33 统计与门禁 / 34 成本·延迟·复盘 |
| 6 | 多智能体 | 35–37 | 35 拆分与协作形态 / 36 A2A / 37 编排（手写 supervisor/handoff） |
| 7 | 统一框架 | 38–40 | **38 LangGraph**（全书最后统一讲，含多智能体图）/ **39 LlamaIndex 的 RAG** / **40 其他技术栈与平台** |
| 8 | 组件封装（副线） | 41–45 | 41 为什么封装 / 42 契约 / 43 决策部件 / 44 治理部件 / 45 装配验证 |

知识点：新增 **C13 向量化与距离度量**、**C14 向量数据库**、**D16 A2A**、**H14 pydantic**；总数 94 → **111**（A9+B21+C14+D16+E14+F18+H14+G5）。

### 3.1 技术栈落位（唯一权威表）

| 技术栈 | 落在哪一章 | 形式 |
|---|---|---|
| pydantic / pydantic-settings | 5 | 独立章 + 在 4/6/11 内联使用 |
| OpenAI SDK（`response_format`/`tools`） | 4、5 | 章内示例 |
| tiktoken | 3、21 | 章内示例 |
| sentence-transformers（bge） | 17、20、22 | 章内示例 |
| qdrant / faiss | 19、22 | 章内示例 |
| rank_bm25 + jieba | 20 | 章内示例 |
| mcp SDK | 13 | 章内示例 |
| **LangChain** | **14**（agent）+ 16（RAG pipeline） | 两处，但**不出现 LangGraph** |
| **LangGraph** | **38**（统一：图/状态/持久化/流式/多智能体） | 只此一章 |
| **LlamaIndex** | **39**（RAG 对照） | 只此一章 |
| **LangFuse + OTel** | **30** | 并入计量章 |
| **RAGAS** | **31** | 并入 RAG 评测章 |
| Agent 评测框架（LangSmith/DeepEval/inspect_ai） | **32** | 并入 Agent 评测章 |
| A2A SDK | 36 | 章内示例 |
| Deep Agents / pydantic-ai / OpenAI Agents SDK / AutoGen / CrewAI / Coze / Dify | **40** | 集中一章 |

---

## 四、代码实例补充清单（按章）

| 章 | 现在 | 补什么 | 库 |
|---|---|---|---|
| 1 | 手造响应 | 真实 SDK 响应对象 + 多模态输入 | `openai` |
| 2 | 手写分布 | 三档温度的真实采样 + logprobs | `openai` |
| 3 | `len//2` 估算 | 真分词、真成本、KV cache 影响 | `tiktoken` |
| 4 | 正则抽 JSON | 五种结构化输出逐一真跑 | `openai`、`pydantic`、`langchain`（仅 4 章内对照 `with_structured_output`） |
| 5 | 无 | pydantic 全量：schema/validator/Settings | `pydantic` |
| 6 | 手写 tool_calls | 真实 `tools=` 往返、并行调用 | `openai` |
| 13 | 手写 JSON-RPC | `mcp` SDK server/client | `mcp` |
| 14 | 无 | LangChain 搭 agent（工具、memory、middleware） | `langchain` |
| 16 | 字符 2-gram | LangChain 端到端 pipeline（含引用校验） | `langchain`、`qdrant`、`sentence-transformers` |
| 17 | 无 | 向量化实脸：归一化、距离、维度、截断、相似度分布 | `sentence-transformers`、`numpy` |
| 18 | 手写切法 | 真实切块器：递归/标题/token/语义 | `langchain-text-splitters`（或 `chonkie`）、`tiktoken` |
| 19 | 手写索引类 | qdrant 的 Flat/IVF/HNSW、payload 过滤、持久化、量化 | `qdrant-client`、`faiss` |
| 20 | 手写 BM25/RRF | 真实 BM25 + 向量 + RRF + CrossEncoder + MMR | `rank_bm25`、`sentence-transformers`、`qdrant` |
| 21 | 字符计 token | `tiktoken` 预算 | `tiktoken` |
| 22 | 手写记忆 | qdrant 三层记忆 | `qdrant`、`sentence-transformers` |
| 23 | 手写存储 | payload 版本过滤 | `qdrant` |
| 24 | 手写沙箱 | 保留（边界是语义） | — |
| 25 | 手写护栏 | 保留 + 一节 LangChain 中间件 | `langchain` |
| 27 | 手写审批 | 保留 + 一节 LangGraph `interrupt()` | `langgraph` |
| 30 | 手写 span | OTel 真 span + LangFuse 上报 | `opentelemetry-sdk`、`langfuse` |
| 31 | 字面重合 | 真实嵌入算指标 + RAGAS 对照 + 评测集 | `ragas`、`sentence-transformers` |
| 32 | 手写裁判 | 评测框架跑同一批用例 | 见第 40 章技术栈 |
| 35/36 | 24 章旧内容 | 拆分判据 + A2A 最小往返 | `a2a-sdk` |
| 37 | 无 | 手写 supervisor/handoff（不引 LangGraph） | 标准库 |
| 38 | 无 | LangGraph 全套 | `langgraph` |
| 39 | 无 | LlamaIndex RAG | `llama-index` |
| 40 | 无 | 各框架最小例子 | `deepagents`?、`pydantic-ai`、`openai-agents`、平台说明 |

---

## 五、执行批次（每章：先概念、后代码、再自查）

| 批 | 章节 | 目标 | 验收 |
|---|---|---|---|
| 0 | 全库重排 | 46 章编号、文件重命名、引用重算 | 引用扫描 0 错、脚本全跑通 |
| 1 | 17、18、19 | RAG 地基三章（向量化/切块/向量库） | 三章各 1–2 个真实库示例 |
| 2 | 16、20 | RAG 主链路（LangChain 端到端、混合重排） | 端到端 pipeline 可跑 |
| 3 | 30、31 | 计量（OTel+LangFuse）、RAG 评测（RAGAS+评测集） | Docker 起 LangFuse 可查 trace |
| 4 | 4、5、6、13、14 | 结构化、pydantic、工具、MCP、LangChain | 各自真实 SDK 往返 |
| 5 | 35–37 | 多智能体拆分、A2A、编排 | A2A 往返 + 两种编排 |
| 6 | 38–40 | LangGraph、LlamaIndex、其他栈 | 每框架最小可跑 |
| 7 | 1、2、3、21、22、23、32 | 补齐剩余真实栈 | 每章至少一处真库 |
| 8 | 41–45 | 副线（可选，最后） | 替换实验通过 |

**三条硬规则**：① 每个示例最多跑 3 次，仍失败写"环境限制"说明；② 代用品必须标注并降为对照；③ 每章概念三段（是什么/不做会坏/最小例子）。

---

## 六、风险与待决

| 风险 | 影响 | 对策 |
|---|---|---|
| 重排 32 个文件 + 上千引用 | 出错面大 | 脚本映射 + 全量引用扫描 + 提交前跑全部脚本 |
| `ragas 0.4.3` 导入失败 | 第 31 章卡住 | 先 `pip install "langchain-community<0.4"` 或降 ragas；3 次失败则写说明 |
| `mcp 2.3` API 改名 | 第 13 章要按 2.x 写 | 用 `MCPServer`；不再用 `FastMCP` |
| HF 直连不通 | 模型下载失败 | 固定 `HF_ENDPOINT=https://hf-mirror.com`，仓库写明 |
| 章节从 42 → 46，篇幅压力 | 每章 10k 字符 | 概念清单驱动：只写"有定义、有失效、有示例"的内容 |

**待你确认两件事**：① 第三节目录是否就是最终结构；② 第 4、6 章里的 `openai` SDK 示例没有 API key，是否允许用"本地 OpenAI 兼容回放服务器"（脚本回放真实响应体，标注为模拟）。
