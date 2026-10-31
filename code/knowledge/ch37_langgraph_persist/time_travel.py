"""LangGraph 的时间旅行：回到某个检查点、改一笔状态、从那里重放。

不联网。一次三节点的运行留下 5 个检查点。取"n3 还没跑"的那一个：
先看原分支，再改一条状态，从同一检查点分叉出另一条路径。

运行：python code/knowledge/ch37_langgraph_persist/time_travel.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class Trace(TypedDict):
    log: Annotated[list[str], operator.add]


def n1(state: Trace) -> dict:
    return {"log": ["n1"]}


def n2(state: Trace) -> dict:
    return {"log": ["n2"]}


def n3(state: Trace) -> dict:
    return {"log": ["n3"]}


def build():
    g = StateGraph(Trace)
    for name, fn in (("n1", n1), ("n2", n2), ("n3", n3)):
        g.add_node(name, fn)
    g.add_edge(START, "n1")
    g.add_edge("n1", "n2")
    g.add_edge("n2", "n3")
    g.add_edge("n3", END)
    return g.compile(checkpointer=InMemorySaver())


def main() -> None:
    app = build()
    thread = {"configurable": {"thread_id": "fork-demo"}}
    print("=== 1. 原分支 ===")
    print(f"  {app.invoke({'log': []}, thread)}")
    history = list(app.get_state_history(thread))
    original_final = history[0].config
    print(f"  检查点数：{len(history)}")
    for snap in history:
        print(f"    step={snap.metadata.get('step'):>2} next={snap.next} "
              f"log={snap.values['log']}")
    print()

    base = next(s for s in history if s.next == ("n3",))
    print("=== 2. 选中的检查点 ===")
    print(f"  step={base.metadata.get('step')} next={base.next} log={base.values['log']}")
    print()

    forked = app.update_state(base.config, {"log": ["人工修正"]})
    state = app.get_state(forked)
    print("=== 3. 改一笔之后：新检查点，原历史不动 ===")
    print(f"  log={state.values['log']} next={state.next}")
    print()

    print("=== 4. 从分叉点重放 ===")
    print(f"  {app.invoke(None, forked)}")
    print(f"  用原检查点的 config 仍能取回原分支："
          f"{app.get_state(original_final).values['log']}")
    print(f"  分叉后 thread 的 head：{app.get_state(thread).values['log']}")
    print()
    print("=== 5. 两条路径的差别 ===")
    print("  原分支：n1 -> n2 -> n3")
    print("  分叉后：n1 -> n2 -> 人工修正 -> n3")
    print("  <- update_state 写的是'到这一步为止的状态'，不是给 n3 的指令")


if __name__ == "__main__":
    main()
