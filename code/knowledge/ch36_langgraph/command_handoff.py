"""LangGraph 的两种跳转：条件边由函数决定，Command 由节点自己决定。

不联网。同一张工单图写两遍，输出同样的路径：
  A. add_conditional_edges：路由是一个独立函数，节点不知道下一站
  B. Command：节点返回下一站，路由知识在节点内部

运行：python code/knowledge/ch36_langgraph/command_handoff.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


class Ticket(TypedDict):
    text: str
    owner: str
    path: Annotated[list[str], operator.add]
    result: str


def triage_plain(state: Ticket) -> dict:
    if "退" in state["text"]:
        return {"path": ["triage"]}
    return {"path": ["triage->human"], "owner": "human"}


def route_plain(state: Ticket) -> str:
    return "billing" if state["path"][-1] == "triage" else "human"


def triage_command(state: Ticket) -> Command:
    if "退" in state["text"]:
        return Command(goto="billing", update={"path": ["triage"], "owner": "billing"})
    return Command(goto="human", update={"path": ["triage->human"], "owner": "human"})


def billing(state: Ticket) -> dict:
    return {"path": ["billing"], "result": "已创建退款单 R-1"}


def human(state: Ticket) -> dict:
    return {"path": ["human"], "result": "已转人工"}


def build_plain():
    g = StateGraph(Ticket)
    g.add_node("triage", triage_plain)
    g.add_node("billing", billing)
    g.add_node("human", human)
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_plain, {"billing": "billing", "human": "human"})
    g.add_edge("billing", END)
    g.add_edge("human", END)
    return g.compile()


def build_command():
    g = StateGraph(Ticket)
    g.add_node("triage", triage_command)
    g.add_node("billing", billing)
    g.add_node("human", human)
    g.add_edge(START, "triage")
    g.add_edge("billing", END)
    g.add_edge("human", END)
    return g.compile()


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def run(app, text: str) -> dict:
    return app.invoke({"text": text, "owner": "", "path": [], "result": ""})


def main() -> None:
    plain = build_plain()
    command = build_command()

    print("=== 1. 同一张工单，两种跳转 ===")
    for text in ("我要退货", "我要投诉"):
        a = run(plain, text)
        b = run(command, text)
        print(f"  工单：{text}")
        print(f"    条件边：path={' / '.join(a['path'])}  result={a['result']}")
        print(f"    Command：path={' / '.join(b['path'])}  result={b['result']}")
    print()

    print("=== 2. 图的形状 ===")
    print("  条件边：triage --[route_plain]--> billing / human")
    print("  Command：triage 自己返回 goto，图上没有 triage->billing 这条边")
    for label, app in (("条件边", plain), ("Command", command)):
        out = [e.target for e in app.get_graph().edges
               if e.source == "triage" and e.target != "__end__"]
        print(f"  {pad(label, 8)}triage 的静态出边：{out}")
    print("  <- Command 的动态跳转不进入静态边，看图时只能看到兜底；"
          "调试要靠 trace，不是靠图")
    print()

    print("=== 3. 选择依据 ===")
    print("  " + pad("写法", 16) + "下一站写在哪      适合")
    print("  " + pad("条件边", 16) + "独立函数里        分支固定、需要看图就懂")
    print("  " + pad("Command", 16) + "节点返回值里      分支由节点内部状态决定、要跨图跳转")
    print("  <- 两者都改变控制流；Command 还能带 update，等价于'跳转 + 写状态'一步完成")


if __name__ == "__main__":
    main()
