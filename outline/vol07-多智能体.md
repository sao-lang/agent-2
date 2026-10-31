# 卷 7 · 多智能体（第 33–35 章）→ D10、H11–H13

> 分册：《Agent 工程》大纲 · 第 7 卷章表
> 全局约定、章号与「写哪章读哪册」见 [docs/OUTLINE.md](../docs/OUTLINE.md)。

**本卷回答**：什么时候该拆成多个 agent，拆完怎么连，跨进程怎么说话。

| 章 | 标题 | 知识点 | 本章要讲透的内容 | 必给的示例 |
|---|---|---|---|---|
| 33 | 拆分与协作：四种拓扑 | D10 | 拆分判据是上下文隔离与通信成本；四种拓扑（supervisor/handoff/blackboard/流水线）与各自失效；讨论式为什么通常不划算；选型表与成本账 | 单/双 agent token 对比；同任务 supervisor 与 handoff 的 agent 数、消息数、延迟 |
| 34 | A2A：跨进程的任务交接 | D10 H12 | agent card / task / message·part / artifact；任务生命周期；与 MCP 的分工；远端 agent 是不可信输入 | 一次最小往返：agent card → task → artifact |
| 35 | 手写编排：三种拓扑 | D10（实现） | 手写 supervisor、handoff、blackboard（含 reducer 与写冲突）；流水线作为对照基线一并实现；与第 38 章框架版对照 | 三种实现跑同一任务；一次写冲突被 reducer 化解 |

---
