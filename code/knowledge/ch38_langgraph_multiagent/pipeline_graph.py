"""LangGraph 版流水线：边就是顺序，阶段契约在节点入口检查。

不联网。正常图三阶段跑通；坏图里 finder 少写一个字段，
writer 在入口显式失败，而不是拿半份数据往下走。

运行：python code/knowledge/ch38_langgraph_multiagent/pipeline_graph.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

import common
from common import EVIDENCE, FINDINGS, LOGS, USAGE, report, write_prompt


class Flow(TypedDict):
    merged: str
    findings: Annotated[list[str], operator.add]
    evidence: Annotated[list[str], operator.add]
    report: str


class ContractError(Exception):
    pass


def reader(state: Flow) -> dict:
    merged = "\n".join(LOGS.values())
    USAGE.add("reader", f"合并日志\n{merged}")
    return {"merged": merged}


def finder(state: Flow) -> dict:
    USAGE.add("finder", f"找错误\n{state['merged']}")
    return {"findings": [FINDINGS[i] for i in (1, 2, 3)],
            "evidence": [EVIDENCE[i] for i in (1, 2, 3)]}


def writer(state: Flow) -> dict:
    if len(state["findings"]) != len(state["evidence"]):
        raise ContractError(
            f"findings {len(state['findings'])} 条，evidence {len(state['evidence'])} 条"
        )
    USAGE.add("writer", write_prompt(state["findings"], state["evidence"]))
    return {"report": report(state["findings"], state["evidence"])}


def build(finder_fn=finder):
    g = StateGraph(Flow)
    g.add_node("reader", reader)
    g.add_node("finder", finder_fn)
    g.add_node("writer", writer)
    g.add_edge(START, "reader")
    g.add_edge("reader", "finder")
    g.add_edge("finder", "writer")
    g.add_edge("writer", END)
    return g.compile()


def run(app=None) -> dict:
    app = app or build()
    common.reset()
    out = app.invoke({"merged": "", "findings": [], "evidence": [], "report": ""})
    return {"out": out, "usage": USAGE}


def main() -> None:
    result = run(build())
    print("=== 1. 正常流水线 ===")
    print(f"  report={result['out']['report']}")
    print(f"  节点调用：{ {k: v['calls'] for k, v in result['usage'].by_agent.items()} }")
    print(f"  总调用={result['usage'].calls} token 估={result['usage'].tokens} "
          f"耗时={result['usage'].ms}ms")
    print()

    def bad_finder(state: Flow) -> dict:
        USAGE.add("finder", f"找错误\n{state['merged']}")
        return {"findings": [FINDINGS[i] for i in (1, 2, 3)]}   # 忘了 evidence

    print("=== 2. 坏流水线：finder 少写一个字段 ===")
    try:
        run(build(bad_finder))
    except ContractError as e:
        print(f"  writer 入口拦住：{e}")
    print("  <- 图的边不检查字段；契约要自己写在节点入口，否则错误会流到下游")
    print()
    print("=== 3. 流水线的形状 ===")
    for e in build().get_graph().edges:
        print(f"  {e.source} -> {e.target}")


if __name__ == "__main__":
    main()
