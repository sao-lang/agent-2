# 卷 9 · 其他框架与平台（第 39–41 章）→ F17 F18、H10

> 分册：《Agent 工程》大纲 · 第 9 卷章表
> 全局约定、章号与「写哪章读哪册」见 [../OUTLINE.md](../OUTLINE.md)。

| 章 | 标题 | 知识点 | 讲哪些 API |
|---|---|---|---|
| 39 | LlamaIndex：摄取与索引 | F18 | `IngestionPipeline`、索引类型、`QueryEngine` |
| 40 | LlamaIndex：Workflow 与检索 | F18 | `Workflow`/事件驱动；与第 13–21 章三版对照 |
| 41 | Deep Agents、pydantic-ai、Agents SDK、AutoGen、CrewAI 与平台 | F17 F18 H10 | Deep Agents 九个内建组件；pydantic-ai 的类型化 agent；OpenAI Agents SDK 的 handoff/guardrail/session；AutoGen/CrewAI；Coze/Dify 的三类隐形状态与导出边界 |

**主线设计 ↔ 框架 API 对照**（每章都要填一行）：

| 主线做法 | 所在章 | LangChain | LangGraph | Deep Agents |
|---|---|---|---|---|
| `tool_calls` 协议 | 6 | `bind_tools` | `ToolNode` | `tools` |
| 最小循环 | 7 | `create_agent` | 图结构 | 内建 |
| 重复检测 | 8 | 无 | 自定义节点 | 部分内建 |
| 上下文裁剪 | 8、19 | `SummarizationMiddleware`/`ContextEditingMiddleware` | 自定义节点 | 自动压缩 |
| 编排的三层 | 22 | LangGraph 图 | 图结构 | `SubagentMiddleware` |
| 外部裁判 | 23 | `RubricGradingMiddleware` | 自定义节点 | `rubric` |
| 状态与 reducer | 24 | `state_schema` | `Annotated` reducer | 内建 |
| 持久化与幂等 | 25 | checkpointer | `Checkpointer` 家族 | `fault-tolerance` |
| 路由 | 13 | 无 | 条件边 | 无 |
| 检索 | 14–18 | Retriever 链 | `ToolNode` 包装 | `retrieval` |
| 长期记忆 | 20 | `BaseStore` | `Store` | `Memory` |
| 沙箱 | 27 | `ShellToolMiddleware` | 自定义 | `sandboxes`/`permissions` |
| 护栏 | 28 | `PIIDetectionMiddleware` | 自定义 | `permissions` |
| 审批 | 30 | `HumanInTheLoopMiddleware` | `interrupt()` | HITL |
| 多智能体拓扑 | 33–35 | 无 | 子图 / `Command` | `subagents` |
| 计量与追踪 | 42 | LangSmith | LangSmith | 内建；LangFuse 接法见 42 |
| 评测 | 43–45 | LangSmith 数据集 | 同上 | 同上 |
| RAG 指标 | 43 | LangSmith evaluators | 无 | RAGAS 复算在 43 |
| 评测集 | 43 | dataset + experiment | 无 | 43 讲怎么建 |
| Agent 轨迹评测 | 44 | LangSmith experiments | 无 | 44 讲四个框架的写法 |
| 可观测上报 | 42 | LangSmith | OTel / LangFuse | 42 |

---
