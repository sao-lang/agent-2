"""LangGraph 的边：条件边决定走哪支，回边构成循环。

不联网。一个客服分流图：
  classify -> refund / tech / human
  refund  -> check -> 通过则 END，不通过回 check（最多两次）

运行：python code/knowledge/ch36_langgraph/graph_edges.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


class Ticket(TypedDict):
    text: str
    path: Annotated[list[str], operator.add]
    attempts: int
    answer: str


def classify(state: Ticket) -> dict:
    if "退" in state["text"]:
        return {"path": ["classify->refund"]}
    if "报错" in state["text"] or "崩" in state["text"]:
        return {"path": ["classify->tech"]}
    return {"path": ["classify->human"]}


def route(state: Ticket) -> str:
    last = state["path"][-1]
    if last.endswith("refund"):
        return "refund"
    if last.endswith("tech"):
        return "tech"
    return "human"


def refund(state: Ticket) -> dict:
    return {"path": ["refund"], "answer": "退款政策：7 天内未拆封可退"}


def tech(state: Ticket) -> dict:
    return {"path": ["tech"], "answer": "请提供报错堆栈与复现步骤"}


def human(state: Ticket) -> dict:
    return {"path": ["human"], "answer": "已转人工"}


def check(state: Ticket) -> dict:
    attempts = state["attempts"] + 1
    ok = "7 天" in state["answer"]
    return {"attempts": attempts, "path": [f"check#{attempts}:{'ok' if ok else 'retry'}"]}


def after_check(state: Ticket) -> str:
    if "7 天" in state["answer"]:
        return "done"
    if state["attempts"] >= 2:
        return "give_up"
    return "retry"


def build():
    g = StateGraph(Ticket)
    g.add_node("classify", classify)
    g.add_node("refund", refund)
    g.add_node("tech", tech)
    g.add_node("human", human)
    g.add_node("check", check)
    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", route, {"refund": "refund", "tech": "tech", "human": "human"}
    )
    g.add_edge("refund", "check")
    g.add_conditional_edges(
        "check", after_check, {"done": END, "retry": "refund", "give_up": "human"}
    )
    g.add_edge("tech", END)
    g.add_edge("human", END)
    return g.compile()


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    app = build()
    cases = ["我要退货", "程序报错了", "你们几点下班"]
    print("=== 1. 三张工单走出的路径 ===")
    for text in cases:
        out = app.invoke({"text": text, "path": [], "attempts": 0, "answer": ""})
        print(f"  {pad(text, 12)}-> {' / '.join(out['path'])}")
        print(f"  {pad('', 12)}   answer={out['answer']}")
    print()

    print("=== 2. 回边：一份不合格的答案会重试 ===")
    # 换一个 check 永远不通过的图，看 attempts 的上限怎么起作用
    g = StateGraph(Ticket)
    g.add_node("classify", classify)
    g.add_node("refund", lambda s: {"answer": "退不了"})
    g.add_node("human", human)
    g.add_node("check", check)
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", route, {"refund": "refund", "tech": "human", "human": "human"})
    g.add_edge("refund", "check")
    g.add_conditional_edges("check", after_check, {"done": END, "retry": "refund", "give_up": "human"})
    g.add_edge("human", END)
    out = g.compile().invoke({"text": "我要退货", "path": [], "attempts": 0, "answer": ""})
    print(f"  path={' / '.join(out['path'])}")
    print(f"  attempts={out['attempts']} answer={out['answer']}")
    print("  <- 回边不是'循环到模型满意'，终止条件必须写在代码里（这里是 attempts>=2）")


if __name__ == "__main__":
    main()
