"""LangGraph 的扇出：Send 把一个节点按列表调用多次。

不联网。输入几份文件，就并行起几个 worker；每个 worker 只拿到自己那一份，
结果通过 reducer 汇总。文件数由运行时输入决定，不是写死的边。

运行：python code/knowledge/ch36_langgraph/send_fanout.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


class Scan(TypedDict):
    files: list[str]
    findings: Annotated[list[str], operator.add]
    calls: Annotated[int, operator.add]


FINDINGS = {
    "a.log": "连接池耗尽",
    "b.log": "重试没有上限",
    "c.log": "超时为零",
    "d.log": "磁盘只读",
    "e.log": "队列积压",
}


def fan_out(state: Scan) -> list[Send]:
    """每个文件发一份数据给同一个节点，而不是把整个文件列表传过去。"""
    return [Send("scan_one", {"file": name}) for name in state["files"]]


def scan_one(payload: dict) -> dict:
    name = payload["file"]
    finding = FINDINGS.get(name, "无异常")
    return {"findings": [f"{name}: {finding}"], "calls": 1}


def build():
    g = StateGraph(Scan)
    g.add_node("scan_one", scan_one)
    g.add_conditional_edges(START, fan_out, ["scan_one"])
    g.add_edge("scan_one", END)
    return g.compile()


def main() -> None:
    app = build()
    print("=== 1. 三个文件 ===")
    out = app.invoke({"files": ["a.log", "b.log", "c.log"], "findings": [], "calls": 0})
    for line in out["findings"]:
        print("  " + line)
    print(f"  worker 调用次数={out['calls']}")
    print()

    print("=== 2. 五个文件：边没有改，扇出数变了 ===")
    out = app.invoke(
        {"files": ["a.log", "b.log", "c.log", "d.log", "e.log"], "findings": [], "calls": 0}
    )
    for line in out["findings"]:
        print("  " + line)
    print(f"  worker 调用次数={out['calls']}")
    print()

    print("=== 3. 空列表：扇出为零，节点一次也不跑 ===")
    out = app.invoke({"files": [], "findings": [], "calls": 0})
    print(f"  findings={out['findings']} calls={out['calls']}")
    print("  <- 这是 Send 与 for 循环的区别：次数由数据决定，图的形状不变")


if __name__ == "__main__":
    main()
