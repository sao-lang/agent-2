"""LangGraph 版 blackboard：Send 扇出，多个 worker 往同一份状态上写，reducer 合并。

不联网。三个 worker 各自读一份日志，只把发现写回；写者最后从共享状态里取。

运行：python code/knowledge/ch38_langgraph_multiagent/blackboard_graph.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

import common
from common import EVIDENCE, FINDINGS, USAGE, read_prompt, report, write_prompt


class Board(TypedDict):
    findings: Annotated[list[str], operator.add]
    evidence: Annotated[list[str], operator.add]
    report: str


def fan_out(state: Board) -> list[Send]:
    return [Send("scan", {"index": i}) for i in (1, 2, 3)]


def scan(payload: dict) -> dict:
    i = payload["index"]
    USAGE.add(f"worker{i}", read_prompt(i))
    return {"findings": [FINDINGS[i]], "evidence": [EVIDENCE[i]]}


def writer(state: Board) -> dict:
    USAGE.add("writer", write_prompt(state["findings"], state["evidence"]))
    return {"report": report(state["findings"], state["evidence"])}


def build():
    g = StateGraph(Board)
    g.add_node("scan", scan)
    g.add_node("writer", writer)
    g.add_conditional_edges(START, fan_out, ["scan"])
    g.add_edge("scan", "writer")
    g.add_edge("writer", END)
    return g.compile()


def run() -> dict:
    common.reset()
    out = build().invoke({"findings": [], "evidence": [], "report": ""})
    return {"out": out, "usage": USAGE}


def main() -> None:
    result = run()
    out = result["out"]
    print("=== 1. blackboard 图 ===")
    print(f"  findings={out['findings']}")
    print(f"  report={out['report']}")
    print(f"  节点调用：{ {k: v['calls'] for k, v in result['usage'].by_agent.items()} }")
    print(f"  总调用={result['usage'].calls} token 估={result['usage'].tokens} "
          f"耗时={result['usage'].ms}ms")
    print()
    print("=== 2. 三个 worker 的写是并行的 ===")
    print("  Send 把三份输入分别投给 scan，三个 scan 之间没有边")
    print("  scan -> writer 这条边等三个 scan 都结束后才走一次")
    print()
    print("=== 3. reducer 保住了什么 ===")
    print("  findings 与 evidence 两个字段都声明了 operator.add；")
    print("  如果换成普通 list，三个 worker 在同一超步写同一字段会报 InvalidUpdateError。")


if __name__ == "__main__":
    main()
