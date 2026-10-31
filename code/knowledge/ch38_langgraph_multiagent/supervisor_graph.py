"""LangGraph 版 supervisor：中心节点决定下一个 worker，收齐后自己写报告。

不联网。与第 35 章手写版的差别只有"控制流写在哪"：
手写版是 while 循环 + 字典分派，这里是一个节点 + 条件边。

运行：python code/knowledge/ch38_langgraph_multiagent/supervisor_graph.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

import common
from common import FINDINGS, USAGE, read_prompt, report, write_prompt


class Team(TypedDict):
    findings: Annotated[list[str], operator.add]
    evidence: Annotated[list[str], operator.add]
    next: str
    round: int
    report: str


def supervisor(state: Team) -> dict:
    done = len(state["findings"])
    if done < 3:
        USAGE.add("supervisor", common.dispatch_prompt(done))
        return {"next": f"w{done + 1}", "round": done + 1}
    USAGE.add("supervisor", write_prompt(state["findings"], state["evidence"]))
    return {"next": "end",
            "round": done,
            "report": report(state["findings"], state["evidence"])}


def route(state: Team) -> str:
    return state["next"]


def make_worker(index: int):
    def worker(state: Team) -> dict:
        USAGE.add(f"worker{index}", read_prompt(index))
        return {"findings": [FINDINGS[index]], "evidence": [common.EVIDENCE[index]]}
    return worker


def build():
    g = StateGraph(Team)
    g.add_node("supervisor", supervisor)
    for i in (1, 2, 3):
        g.add_node(f"w{i}", make_worker(i))
    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor", route,
        {"w1": "w1", "w2": "w2", "w3": "w3", "end": END},
    )
    for i in (1, 2, 3):
        g.add_edge(f"w{i}", "supervisor")
    return g.compile()


def run() -> dict:
    common.reset()
    out = build().invoke(
        {"findings": [], "evidence": [], "next": "", "round": 0, "report": ""}
    )
    return {"out": out, "usage": USAGE}


def main() -> None:
    result = run()
    out = result["out"]
    rows = result["usage"].by_agent
    print("=== 1. supervisor 图 ===")
    print(f"  report={out['report']}")
    print(f"  节点调用：{ {k: v['calls'] for k, v in rows.items()} }")
    print(f"  总调用={result['usage'].calls} token 估={result['usage'].tokens} "
          f"耗时={result['usage'].ms}ms")
    print()
    print("=== 2. 图长什么样 ===")
    edges = [(e.source, e.target) for e in build().get_graph().edges]
    for src, dst in edges:
        print(f"  {src} -> {dst}")
    print("  <- 三个 worker 都回到 supervisor；谁下一个由 supervisor 的返回值决定")


if __name__ == "__main__":
    main()
