# 卷 8 · LangGraph（第 36–38 章）→ F11–F16、H11

> 分册：《Agent 工程》大纲 · 第 8 卷章表
> 全局约定、章号与「写哪章读哪册」见 [docs/OUTLINE.md](../docs/OUTLINE.md)。

**本卷回答**：图、状态、持久化与流式在框架里怎么落，多智能体编排怎么用 API 表达。

| 章 | 标题 | 知识点 | 讲哪些 API |
|---|---|---|---|
| 36 | 图、状态与运行时 | F11 F12 F13 F14 | reducer；`add_node`/`add_edge`/`add_conditional_edges`；`Send`/`Command`；`compile` 参数；函数式 API 与图 API 的取舍 |
| 37 | 持久化、时间旅行与流式 | F15 F16 | `Checkpointer` 家族；`thread_id`/`checkpoint_ns`；`get_state_history`/`update_state`；5 种 `stream_mode`；`astream_events` v2 |
| 38 | 多智能体编排 | H11 H13 | supervisor / handoff / 黑板 / 讨论式的框架实现；交接单与共享工作区；trace 跨 agent 串联与成本归因 |

---
