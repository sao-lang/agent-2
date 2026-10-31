"""LangGraph 版 handoff：一个节点处理完当前棒次，用 Command 把控制权交给下一棒。

不联网。与 supervisor 的区别：没有中心节点，节点自己返回 goto；
每一棒只看到交接上下文，不看到其他 agent 的完整输入。

运行：python code/knowledge/ch38_langgraph_multiagent/handoff_graph.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import common
from common import EVIDENCE, FINDINGS, LOGS, USAGE, SYSTEM, report, write_prompt


class Handoff(TypedDict):
    idx: int
    context: Annotated[list[str], operator.add]
    report: str


def agent(state: Handoff) -> Command:
    i = state["idx"] + 1
    prompt = (
        f"{'x' * SYSTEM}\n"
        f"# 任务\n读日志 {i}，补一条发现，然后交给下一棒。\n"
        f"# 交接上下文\n{state['context']}\n"
        f"# 日志\n<<<\n{LOGS[i]}\n>>>"
    )
    USAGE.add(f"agent{i}", prompt)
    update = {
        "idx": i,
        "context": [f"{FINDINGS[i]}（{EVIDENCE[i]}）"],
    }
    if i < 3:
        return Command(goto="agent", update=update)
    return Command(goto="writer", update=update)


def writer(state: Handoff) -> dict:
    findings = [c.split("（")[0] for c in state["context"]]
    evidence = [c.split("（")[1].rstrip("）") for c in state["context"]]
    USAGE.add("writer", write_prompt(findings, evidence))
    return {"report": report(findings, evidence)}


def build():
    g = StateGraph(Handoff)
    g.add_node("agent", agent)
    g.add_node("writer", writer)
    g.add_edge(START, "agent")
    g.add_edge("writer", END)
    return g.compile()


def run() -> dict:
    common.reset()
    out = build().invoke({"idx": 0, "context": [], "report": ""})
    return {"out": out, "usage": USAGE}


def main() -> None:
    result = run()
    out = result["out"]
    print("=== 1. handoff 图 ===")
    print(f"  report={out['report']}")
    print(f"  节点调用：{ {k: v['calls'] for k, v in result['usage'].by_agent.items()} }")
    print(f"  总调用={result['usage'].calls} token 估={result['usage'].tokens} "
          f"耗时={result['usage'].ms}ms")
    print()
    print("=== 2. 图长什么样 ===")
    for e in build().get_graph().edges:
        if e.target != "__end__":
            print(f"  {e.source} -> {e.target}")
    print("  <- agent 没有静态出边；下一站写在 Command 的 goto 里")
    print("     代价是看图看不出流程，必须读代码或看 trace")


if __name__ == "__main__":
    main()
