"""跨 agent 的 trace 与成本归因：一次运行里，每个 agent 各花了多少。

不联网。用 astream_events 拿到节点级事件，用 common.USAGE 拿到每个 agent
的调用次数与 token。两者用同一次运行对齐，就是一张成本归因表。

运行：python code/knowledge/ch38_langgraph_multiagent/trace_cost.py
"""

from __future__ import annotations

import asyncio

import common
import supervisor_graph


async def collect() -> None:
    common.reset()
    app = supervisor_graph.build()
    spans: list[tuple[int, str, str]] = []
    async for ev in app.astream_events(
        {"findings": [], "evidence": [], "next": "", "round": 0, "report": ""},
        version="v2",
    ):
        if ev["event"] not in ("on_chain_start", "on_chain_end"):
            continue
        name = ev.get("name", "")
        if name not in ("LangGraph", "supervisor", "w1", "w2", "w3"):
            continue
        spans.append((len(ev["parent_ids"]), ev["event"], name))

    print("=== 1. 一次运行的节点树 ===")
    for depth, event, name in spans:
        mark = "开始" if event == "on_chain_start" else "结束"
        print("  " + "  " * depth + f"{name} {mark}")

    print()
    print("=== 2. 成本按 agent 归因 ===")
    print("  " + common.pad("agent", 12) + common.pad("调用", 6)
          + common.pad("token", 8) + "耗时ms")
    total = 0
    for agent, row in common.USAGE.by_agent.items():
        print("  " + common.pad(agent, 12) + common.pad(str(row["calls"]), 6)
              + common.pad(str(row["tokens"]), 8) + str(row["calls"] * common.CALL_MS))
        total += row["tokens"]
    print(f"  合计 token={total}，调用={common.USAGE.calls}")
    print()
    print("=== 3. 这张表能回答什么 ===")
    print("  - 钱花在哪个 agent 上：supervisor 的 4 次调用占了多少")
    print("  - 哪个 agent 是瓶颈：调用次数 × 单次耗时")
    print("  - 一次 trace 是否跨 agent：每个节点都是同一个 trace 的子 span")


if __name__ == "__main__":
    asyncio.run(collect())
