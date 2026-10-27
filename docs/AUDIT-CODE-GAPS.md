# 代码示例缺口清查（AUDIT-CODE-GAPS）

> 目的：回答一个问题——**每一章的知识点，正文里到底有没有对应的、用真实技术栈跑出来的代码。**
> 方法：先机械扫描（脚本 `audit_code.py`，见附录），再逐章人工判定。
> 结论日期：2026-10-28。范围：已写的第 0–31 章 + 待写的卷 6（第 32–43 章）。

---

## 一、一句话结论

**已写的 32 章里，示例对第三方库的依赖是 0。** 需要真实技术栈的章节（RAG 全流程、MCP、结构化输出、评测、可观测、多智能体）全部用手写近似替代，其中第 14–19、24、28 章已经到"章节名不副实"的程度。

---

## 二、根因：三条规则叠加的结果

| # | 规则（出处） | 本意 | 副作用 |
|---|---|---|---|
| 1 | "示例只用 Python 标准库，离线可跑，不要求先装框架"（README「代码」） | 保证任何机器都能跑 | 卷 3 起，凡是"库才是主题"的章节也退回手写 |
| 2 | "假后端 + 原理演示"（第 0 章、卷 1–2 的约定） | 让模型调用可复现 | 被沿用到嵌入/向量库/评测，变成"假嵌入 + 假指标" |
| 3 | 框架整体独立成卷 6（v5 的结构决定） | 主线只讲原理 | 主线失去了"真实技术栈"的示范，读者学不到怎么落地 |

三条叠加的后果：**原理讲得清楚，但读者照着做不出一个用真实库的系统。** 第 15 章最典型——标题是"切块与向量检索"，全文没有一个真实的切块器、嵌入模型或向量库调用。

---

## 三、逐章清查表

判定口径：
- **P0**：章节主题就是某项技术栈，现在没有真实实现 → 必须补。
- **P1**：有真实实现会更可信、且不影响主线结构 → 应补。
- **P2**：手写是合理的（主题是语义而非库），只补一句"框架/库对应什么"。
- **—**：无需改动。

| 章 | 现状（示例与核心实现） | 该有的真实栈 | 缺的具体代码 | 优先级 |
|---|---|---|---|---|
| 0 起点 | 3 个示例，纯概念对照 | — | — | — |
| 1 四个字段 | 构造假响应 JSON，手写解析 | `openai` SDK 的真实请求/响应对象 | 一次真实 `client.chat.completions.create` 的请求体、响应对象与 `model_dump()`；`usage`/`finish_reason` 原样打印 | P1 |
| 2 为什么编/温度 | 手写概率分布、温度对 logits 的影响 | 真实 API 的 `temperature`/`top_p` + 多次采样 | 同一提示 3 档温度各 5 次的真实输出对比（无 key 时用本地兼容服务器回放真实响应体） | P1 |
| 3 token 与成本 | 用 `len(text)//2` 估算 | `tiktoken`（cl100k/o200k）+ 厂商 usage 校准 | 三种文本的 tiktoken 真实 token 数、估算偏差表、成本计算 | P0 |
| 4 结构化输出 | 正则抽 JSON、手写重试、手写 schema 校验 | `openai` 的 `response_format`/`json_schema`、`pydantic` 校验、`langchain.with_structured_output` 三策略 | 五种做法的真实调用与失败输出（json mode 缺字段、schema 严格模式、function calling、本地校验自愈） | P0 |
| 5 工具调用 | 手写 `tool_calls` JSON 与手工执行 | `openai` 的 `tools=` 往返、`langchain` 的 `bind_tools` | 真实请求体 + 真实 `tool_calls` 响应 + 回灌；`bind_tools` 对照 | P0 |
| 6 最小循环 | 手写 while + 三态终止 | —（主题就是循环语义） | 只加一句"框架里对应 `create_agent`（第 35 章）" | P2 |
| 7 四种失控 | 手写守卫与指纹 | — | — | P2 |
| 8 编排范式 | 手写 FSMDAG、串并行耗时 | `langgraph` 对照（卷 6 第 36 章） | 一句对照 + 指向 | P2 |
| 9 反思 | 手写裁判 | `ragas`/LLM 裁判（卷 6 第 41 章） | 一句对照 + 指向 | P2 |
| 10 状态 | 手写 State/reducer | — | — | — |
| 11 持久化 | 手写 JSON 检查点（`sqlite3` 是标准库） | — | — | P2 |
| 12 MCP 与 Skill | **手写 JSON-RPC 充当 MCP server** | `mcp` 官方 SDK（2.3：`MCPServer`） | 一个真实 `MCPServer`（暴露 2 个工具）+ `ClientSession` 调用；手写版降级为"协议讲解" | P0 |
| 13 分流 | 手写规则/小模型/大模型路由 | 真实 embedding 路由 或 LLM 路由 | 一个用 bge 向量做意图路由的真实实现 + 兜底率统计 | P1 |
| 14 RAG 四环节 | `grams()` + 手写 cosine + 手写检索 | 真实嵌入 + 向量库 + LLM 生成 + 引用校验 | **端到端 pipeline**：切块→嵌入→入库→检索→装配→生成→逐句引用校验，全链路真跑 | P0 |
| 15 切块与向量检索 | **字符 2-gram 向量 + 手写三种索引**；正文自述"代替真实嵌入" | `langchain-text-splitters`、`sentence-transformers`（bge-small-zh）、`qdrant`/`faiss`、`rank_bm25`+`jieba` | 真实切块器（Recursive/MarkdownHeader）对比、真实嵌入的召回、三种索引在真实库上的召回/耗时 | P0 |
| 16 混合检索与重排 | 手写 BM25 类、手写 RRF、手写 `rerank_score` | `rank_bm25`、`sentence-transformers` CrossEncoder（bge-reranker）、faiss/qdrant | 真实 BM25、真实向量召回、RRF 融合、CrossEncoder 重排前后 Top-5 | P0 |
| 17 上下文装配 | 字符数当 token、手写槽位 | `tiktoken`/`AutoTokenizer` 真实计数 | 用真实 tokenizer 做四槽位预算与压缩，输出占用表 | P1 |
| 18 长期记忆 | 手写记录 + 字面重合召回 | `qdrant` + bge 嵌入做记忆检索 | 三层记忆的真实写入与召回（含租户过滤、软删除） | P1 |
| 19 知识治理 | 手写块存储与字面检索 | 向量库的 metadata 过滤 + 版本字段 | 增量更新后按 `version`/`active` 过滤的真实检索 | P1 |
| 20 沙箱 | 标准库路径/网络/超时演示 | —（主题是边界，不是库） | — | — |
| 21 护栏 | 真实 `sqlite3` 只读连接 ✓ | — | 可选：`presidio` 做 PII（非必须） | — |
| 22 注入 | 手写攻击面与检测器 | —（原理为主） | 可选：用真实嵌入/分类器做注入检测 | P2 |
| 23 审批 | 手写状态机与续跑 | — | — | — |
| 24 多智能体 | **只有拆分判据、成本对照、并发写**；无任何 agent↔agent 协议 | `a2a-sdk`（`a2a.types.AgentCard/Task/Message`、`a2a.client`）、`langgraph` 的 supervisor/handoff | **A2A 一节 + 最小往返**：agent card 发现、task 生命周期、message/part、artifact；supervisor vs handoff 两种编排 | **P0** |
| 25 对外形态 | 标准库 SSE 服务 ✓ | —（主题是协议） | 可选：FastAPI/Starlette 对照 | P2 |
| 26 交付 | 模拟 Dockerfile/镜像体积 | `docker` 真构建（环境已可用） | 两条 Dockerfile 真 build 的体积与关闭行为 | P2 |
| 27 计量与可观测 | 手写 span/JSONL；OTel 段只是"字段映射表" | `opentelemetry-sdk` 真 span 树 + `langfuse` 真上报 | 用 OTel SDK 打一棵真 span 树、导出 OTLP/JSON；接 LangFuse 看同一棵树 | P0 |
| 28 RAG 评测 | 字面重合当四指标 | `ragas`（0.4.3，需先修依赖） | 用 ragas 复算四指标 + 与手算对照 + dataset 格式 | P0 |
| 29 Agent 评测 | 手写裁判与 kappa | `ragas` 的 judge 或 `langfuse` evaluator | 裁判与人工一致性用真实评审器跑一遍 | P1 |
| 30 统计与门禁 | 手写 Wilson/门禁 | `scipy.stats`（可选） | 不必须；可加 scipy 对照一行 | P2 |
| 31 成本/延迟/复盘 | 手写瀑布与复盘 | `langfuse` 导出的真实用量（与 27 配套） | 用 LangFuse 的真实 trace 汇总成本瀑布与延迟 | P1 |

### 卷 6（第 32–43 章，待写）

卷 6 天然是真实栈，但要防止两个反向问题：**① 只贴 API 不跑；② 与主线脱节。** 每章至少满足：一个可运行示例 + 一处"替代主线哪一章"的对照。第 42 章（多智能体与 A2A）与第 24 章的分工见第五节。

---

## 四、RAG 全流程的缺口（第 14–19 章合起来看）

用户的原话是"整个 RAG 的流程都应该有直接的代码示例"。按流程逐环节核对：

| 环节 | 现在有没有真实代码 | 缺什么 |
|---|---|---|
| 文档解析 | 无 | markdown/PDF 解析成结构化文本（`unstructured` 或 `markdown`） |
| 清洗与去噪 | 无 | 去页眉页脚、去重复段、保留表格 |
| 切块 | 有，但手写 | `langchain-text-splitters` 的 Recursive/MarkdownHeader，含 overlap 与 token 计数 |
| 嵌入 | **无**（2-gram 代替） | `sentence-transformers` + `bge-small-zh-v1.5`（已在本机跑通，dim 512） |
| 入库 | **无** | `qdrant`（本地模式）或 `faiss` 建集合、写 payload、建索引 |
| 稠密检索 | 有，但手写 cosine | 向量库 `query_points` 真实返回（含 payload 过滤） |
| 稀疏检索 | 手写 BM25 | `rank_bm25` + `jieba` 分词 |
| 融合 | 手写 RRF | 真实两路结果的 RRF |
| 重排 | 手写打分 | `CrossEncoder`（bge-reranker-base）真重排 |
| 查询改写 | 无 | LLM 改写/多查询（可用脚本化模型或真实 API） |
| 上下文装配 | 有，字符计 | `tiktoken` 计 token + 引用编号 |
| 生成 | 脚本化 | 带引用约束的 prompt + 结构化输出（第 4 章） |
| 引用校验 | 手写字面比对 | 断言→块的回链（可用嵌入相似度 + 规则） |
| 增量更新 | 手写软删 | 向量库 payload 版本过滤 + 重建流程 |

**建议**：第 14 章给出**一条端到端 pipeline**（切块→嵌入→入库→检索→装配→生成→引用校验），第 15–18 章各自把其中一环换成真实库并对比手写版。这样"整个流程都有代码"落在第 14 章，其余章做深挖。

---

## 五、多智能体与 A2A 专项（第 24 章）

### 现状
第 24 章只有三件事：拆分判据（`split_criteria.py`）、单/双 agent 成本对照（`token_compare.py`）、并发写（`overwrite_conflict.py`）。**没有任何 agent 与 agent 之间的协议代码**，A2A 完全缺失。

### 缺的内容（应补进第 24 章，而不是只放在卷 6）
| 要讲 | 具体代码 |
|---|---|
| agent card 与发现 | 用 `a2a.types.AgentCard` 构造能力声明（技能、输入输出模态、鉴权方式），`A2ACardResolver` 读取 |
| task 生命周期 | `submitted → working → input-required → completed/failed/canceled` 的状态机；用 `a2a.types.Task`/`TaskStatus` 真类型 |
| 消息结构 | `Message` + `Part`（文本/文件/结构化数据）；一次任务里多轮消息 |
| 产物 | `Artifact`：远端 agent 交回的可引用结果 |
| 与 MCP 的分工 | 一张对照表 + 两个最小例子：MCP 给工具、A2A 给任务 |
| 编排形态 | supervisor（一个主 agent 分派）vs handoff（对等交接）vs 讨论式；用 `langgraph` 各实现一次 |
| 信任边界 | 远端 agent 的返回是**不可信输入**（接第 22 章），委派要带能力范围与凭据；trace 用 `traceparent` 跨 agent 串起来（接第 27 章） |

### 与卷 6 第 42 章的分工
- **第 24 章（主线）**：说清"拆开之后靠什么说话"，给 A2A 的对象与最小往返；不依赖框架。知识点并入 **D10**（多 Agent），章名改为「多 Agent：拆分、交接与 A2A」。
- **第 42 章（卷 6）**：说清"框架怎么编排多个 agent"——H11 编排形态（supervisor/handoff/讨论）、H12 跨框架互操作、H13 多智能体成本与可观测。
- 两章共用同一条判据：**协议解决"跨系统"，编排解决"同一系统内"**。

> 大纲已按此更新：D10 增补 A2A 四个对象与最小往返；H11–H13 改为编排形态 / 互操作 / 成本与可观测；知识点总数仍为 107。

### 可行性（已探测）
`a2a-sdk 1.3.0` 已安装，`a2a.types` 有 `AgentCard`/`Task`/`Message`/`Part`，`a2a.client` 有 `A2ACardResolver` 与 `Client`；`a2a.server` 只导出子模块，需按其 1.x 结构写（待验证一轮）。

---

## 六、评测链缺口（第 28–31 章 + 卷 6 第 39–41 章）

| 章 | 现状 | 缺什么 |
|---|---|---|
| 28 RAG 评测 | 字面重合当 faithfulness/precision/recall/relevancy | `ragas` 的真实指标（先修依赖），并保留"手算版"作对照——**两者数不一样才讲得清指标口径** |
| 29 Agent 评测 | 手写裁判 + kappa | 一个真实评审器（ragas judge / langfuse evaluator）与人工标注的一致性 |
| 30 统计 | Wilson 手算 | 可加 `scipy.stats` 对照（非必须） |
| 31 成本/延迟 | 手写瀑布 | 用第 27 章接的 LangFuse 真实用量汇总 |

环境注意：`ragas 0.4.3` 当前导入失败（`langchain_community.chat_models.vertexai` 缺失，因 langchain-community 0.4 移除）。修复方案二选一：`pip install "langchain-community<0.4"` 或降到 `ragas==0.2.*`。这是写第 28/40 章前必须先解决的事。

---

## 七、环境与可行性（本机实测）

| 库 | 状态 | 备注 |
|---|---|---|
| `tiktoken` | ✅ | `cl100k_base` 可用，无下载失败 |
| `sentence-transformers` + `BAAI/bge-small-zh-v1.5` | ✅ | 首次下载 94s（走 `HF_ENDPOINT=https://hf-mirror.com`），dim=512，相似度正常 |
| `qdrant-client` | ✅ | 本地 `:memory:` 模式可用 |
| `faiss-cpu` | ✅ | 1.15.1，`IndexFlatIP` 可用 |
| `rank_bm25` + `jieba` | ✅ | BM25 排序正常 |
| `langchain` / `langgraph` / `langchain-text-splitters` | ✅ | 1.4.7 / 1.2.18 / 1.1.3 |
| `mcp` | ⚠️ | 2.3.0，`FastMCP` 已改名 `MCPServer`（示例要按 2.x 写） |
| `a2a-sdk` | ⚠️ | 1.3.0，顶层无导出，按 `a2a.types`/`a2a.client` 子模块写 |
| `ragas` | ❌ | 0.4.3 导入失败，需修依赖后使用 |
| `langfuse` | ✅ | 2.60.10；本机 Docker 有 `langfuse/langfuse:2` 镜像，可起 v2 服务 |
| `opentelemetry-sdk` | ✅ | 1.45.1 |
| `openai` | ✅ | 1.109.1（无 API key，需用本地兼容服务器或脚本化模型） |

---

## 八、修复顺序与工程量

| 批 | 内容 | 章 | 预估 |
|---|---|---|---|
| 1 | RAG 全链路真实化 | 14、15、16 | 每章重写 1–2 个示例 + 正文局部改写 |
| 2 | 协议与结构化 | 4、5、12 | 各 1 个真实 SDK 示例 |
| 3 | 多智能体与 A2A | 24（新增一节 + 1 个示例） | 最大一块新内容 |
| 4 | 计量与评测 | 27、28（+29、31） | 先修 ragas，再接 LangFuse |
| 5 | 其余 P1/P2 | 1、2、3、13、17、18、19、26 | 逐个替换或补对照 |
| 6 | 卷 6 写作 | 32–43 | 按新规则，每章真库 |

### 规则修改（防复发）
1. README「代码」改为**分层规则**：卷 1–2 允许脚本化后端；**卷 3 起，凡"库即主题"的章节必须给真实库实现**；每章至少一处真实栈。
2. WRITING-SPEC 增加"示例技术栈"一节：手写版与真实库版**成对出现**，手写版只用于讲原理。
3. OUTLINE 的章节表增加一列"示例技术栈"，写本章要用到的库（如 15：langchain splitters / bge / qdrant / rank_bm25）。
4. 示例允许联网下载模型（首次），仓库附 `requirements.txt` 与 `HF_ENDPOINT` 说明。

---

## 附录：机械清查原始输出

```
章     py块    全部块     示例文件     行数  真实库                         代用品标记
00      3     16        3    282  -                           脚本化的假后端,假后端
01      1     19        6    624  -                           原理演示,演示用
02      3      9        4    314  -                           原理演示
03      7     15        4    325  -                           原理演示,演示用
04     14     22        3    381  -                           原理演示,假后端
05     11     26        5    750  -                           模拟
06      6     13        3    316  -
07      6     13        2    218  -                           原理演示,不是实测
08      6      9        2    190  -                           原理演示,不是实测
09      6     17        2    134  -
10     10     17        1    112  -                           模拟
11      8     19        1    107  -                           原理演示,模拟
12      7     18        2    210  -
13      3      7        1    147  -
14      3      6        1    151  -                           示意,不是实测
15      2      7        1    268  -                           代替真实,字符 2-gram,示意
16      3      6        1    223  -                           字面重合,模拟
17      3      8        1    214  -
18      3      7        1    133  -
19      4     10        1    175  -
20      6     13        6    689  -
21      5     13        5    551  -                           原理演示,代替真实
22      3      7        3    313  -
23      5     12        3    398  -
24      2      7        3    274  -
25      2      7        2    310  -                           模拟
26      2      7        2    311  -                           示意
27      5     12        3    417  -                           模拟
28      4      8        2    299  -                           字面重合
29      2      7        3    363  -
30      2      7        2    190  -
31      0     10        3    305  -
```
