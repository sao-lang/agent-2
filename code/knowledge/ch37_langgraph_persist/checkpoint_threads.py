"""LangGraph 的检查点：thread_id 隔离、继续对话、查看历史。

不联网。同一个编译后的图，用两个 thread_id 跑两次：
  t1 先跑一轮，再追加一轮；两轮的状态是累加的
  t2 从零开始，看不到 t1 的任何东西

运行：python code/knowledge/ch37_langgraph_persist/checkpoint_threads.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class Chat(TypedDict):
    log: Annotated[list[str], operator.add]
    turns: Annotated[int, operator.add]


def load(state: Chat) -> dict:
    return {"log": ["load"]}


def answer(state: Chat) -> dict:
    return {"log": ["answer"], "turns": 1}


def build():
    g = StateGraph(Chat)
    g.add_node("load", load)
    g.add_node("answer", answer)
    g.add_edge(START, "load")
    g.add_edge("load", "answer")
    g.add_edge("answer", END)
    return g.compile(checkpointer=InMemorySaver())


def config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def main() -> None:
    app = build()

    print("=== 1. 两个 thread_id 各自独立 ===")
    a = app.invoke({"log": [], "turns": 0}, config("t1"))
    b = app.invoke({"log": [], "turns": 0}, config("t2"))
    print(f"  t1: {a}")
    print(f"  t2: {b}")
    print()

    print("=== 2. 同一个 thread 再跑一轮：状态是接着的 ===")
    c = app.invoke({"log": ["second"], "turns": 0}, config("t1"))
    print(f"  t1 第二轮: {c}")
    print(f"  t2 仍是: {app.get_state(config('t2')).values}")
    print()

    print("=== 3. 检查点历史（t1）===")
    history = list(app.get_state_history(config("t1")))
    print(f"  共 {len(history)} 个检查点")
    for snap in history:
        print(f"    step={snap.metadata.get('step'):>2} next={snap.next} "
              f"values={snap.values}")
    print()
    print("  <- 历史里每一个检查点都是一份完整状态，不是一份 diff")
    print("     thread_id 是隔离键；checkpoint_ns 区分子图，普通图里为空")


if __name__ == "__main__":
    main()
