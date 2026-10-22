# 附录 B 技术栈索引

> 每个技术在哪些章出现，**学到什么程度就够**。

---

## B.1 核心依赖（`requirements.txt`）

| 包 | 版本 | 用在 | 学到什么程度 |
|---|---|---|---|
| `langgraph` | 1.2.16 | 第 5、6、9、19、25 章 | **系统学**（本书唯一必须深入的框架） |
| `langchain` | 1.4.7 | 第 4、6、9 章 | 只用消息类型与少量工具封装 |
| `langchain-openai` | 1.7.2 | 全书 | 只用 `ChatOpenAI` + `bind_tools` + `with_structured_output` |
| `langgraph-checkpoint-sqlite` | 2.0.11 | 第 9 章 | 会 `SqliteSaver` + `get_state_history` 就够 |
| `pydantic` | 2.14.1 | 全书 | **系统学**（结构化输出的基础） |
| `structlog` | 26.1.0 | 第 1 章 | 了解 JSON 日志即可 |
| `tenacity` | 9.2.1 | 第 3、8 章 | 会 `retry` + `stop_after_attempt` 即可 |
| `numpy` | 2.x | 第 11、12 章 | 只用点积与 argsort |

---

## B.2 按能力域索引

### 计量与观测

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| OpenTelemetry 语义约定 | 2 | `gen_ai.*` 属性命名 | Collector 部署、采样策略细节 |
| Langfuse | 2 | 接 callback、看 trace | 自建高可用部署 |
| structlog / loguru | 1 | JSON 结构化日志 | 复杂 processor 链 |
| `time.perf_counter` | 1、22 | 只要知道它单调递增、适合计时 | — |

### 编排

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| LangGraph `StateGraph` | 5、6 | 节点/边/条件边/`END` | — |
| `Annotated[list, reducer]` | 9、25 | **必学**（不加会丢数据） | 自定义复杂 reducer |
| `interrupt` / `Command(resume)` | 9、19 | **必学**（HITL 基础） | 复杂嵌套中断 |
| `Send`（动态 fan-out） | 25 | 会传 state dict | 超大 fan-out 的性能调优 |
| `checkpointer` | 9 | `InMemorySaver` + `SqliteSaver` | 自定义 checkpointer 后端 |
| `get_state_history`（时间旅行） | 9 | 会列出检查点 | 跨版本迁移 |
| `TypedDict` State | 全书 | **必学**（用裸 dict 会踩坑） | — |

### 检索

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| 向量检索（余弦/点积） | 11 | 手写一遍理解原理 | — |
| BM25 | 12 | 手写一遍（会算 tf/idf 饱和） | 参数调优的论文细节 |
| RRF | 12 | 公式 + `k=60` 的含义 | — |
| Rerank 模型 | 12 | 知道双塔 vs 交叉编码器的差别 | 具体模型选型基准 |
| Embedding 模型 | 11 | 会换模型 + 重建索引 | 训练嵌入模型 |
| Qdrant / pgvector / Milvus | 11 | 能把 `Index.search` 换掉 | 分布式部署与分片 |
| GraphRAG | 14 | 实体抽取 + BFS 扩展 + 社区摘要 | Leiden 算法细节 |

### 数据与存储

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| SQLite（`check_same_thread`） | 9、17、23 | 会用 + 知道线程限制 | WAL/并发调优 |
| Redis | 9（延伸） | 知道能做 checkpointer/缓存 | 集群方案 |
| Docker（沙箱参数） | 20 | `--network none` / `--read-only` / `--pids-limit` / `--cap-drop` | 编排、网络插件 |
| Playwright | 项目 B | `get_by_role` / `expect` / `wait_for_load_state` | 复杂录制回放 |

### 安全

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| 正则（护栏） | 18 | 会写"宽松间隔匹配"，知道误杀/漏杀权衡 | 复杂回溯优化 |
| PII 脱敏 | 18 | **顺序 + 边界**（这两点最容易错） | 完整 PII 识别模型 |
| 提示注入防御 | 18 | 直接 + 间接（文档）两路 | 对抗样本生成 |
| OWASP LLM Top 10 | 18 | 读一遍 LLM01/LLM06 | 全部条目 |

### 评测

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| recall@k / MRR | 11、12、15 | 会算、会解释 | — |
| RAGAS 指标（faithfulness 等） | 15 | 手写一遍再对照 | 全部 20+ 指标 |
| LLM-as-judge | 15 | **必须做 judge 校验** | 复杂偏好对齐 |
| pytest | 26、28 | 会写门禁测试 | 插件生态 |
| 轨迹评估 | 26 | 重复检测 + 预算检测 | — |

### 成本与延迟

| 技术 | 章节 | 学到什么程度 | 不必学 |
|---|---|---|---|
| 成本归因 | 21 | 按 stage 打标签 + 报表 | 复杂财务对账 |
| 语义缓存 | 21 | 知道阈值 ≥0.92 才安全 | 向量索引加速 |
| asyncio（`gather` + Semaphore） | 22 | 会限并发 | 事件循环底层 |
| SSE | 22 | 关 buffering + 心跳 + 事件类型 | 复杂重连协议 |

### AI 写作工具（可选）

| 技术 | 章节 | 学到什么程度 |
|---|---|---|
| Ollama | 0（环境） | 会 `pull` + 配 `base_url` 即可 |
| uv | 0（环境） | 会把 `pip install` 换成 `uv pip install` |

---

## B.3 本书**没有**讲的（按需自学）

| 内容 | 为什么没讲 | 什么时候需要 |
|---|---|---|
| 模型微调（LoRA/QLoRA） | 与应用工程弱相关 | 有稳定数据+明确收益时 |
| Kubernetes 部署 | 本书只到 Docker | 上规模 |
| 前端框架细节（React/Vue） | 假设你会 | 项目 A/B/C 的前端 |
| 向量数据库的高可用/分片 | 属于 DBA 范畴 | QPS 很高时 |
| 多模态（图像/音频）Agent | 单独一本书的量 | 做 computer use 深入时 |
| A2A 协议细节 | 生态尚未成熟 | 跨组织协作 |

---

## B.4 版本说明（重要）

本书代码在以下版本**实际运行验证**：

```
Python  3.11–3.13
langgraph 1.2.16
langchain 1.4.7
langchain-openai 1.7.2
pydantic 2.14.1
```

⚠️ **如果 `langchain` 升到 0.x 时代的写法（`AgentExecutor` / `agent_scratchpad`），说明你参考了旧资料，与本书不兼容。**

**升级建议**：先跑 `pytest`，绿了再升。不要"为了新而新"——本书讲的所有原则与框架版本无关。
