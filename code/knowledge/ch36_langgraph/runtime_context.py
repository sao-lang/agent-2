"""LangGraph 的运行时：Runtime 把"这次运行的上下文"与"要持久化的状态"分开。

不联网。两个节点读取同一个租户 id：
  state 里的字段会进入检查点、会被 reducer 合并
  context 里的字段只对本次运行可见，不进检查点

运行：python code/knowledge/ch36_langgraph/runtime_context.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime


class State(TypedDict):
    answer: str
    path: Annotated[list[str], operator.add]


class Context(TypedDict):
    tenant: str
    budget_tokens: int


def load(state: State, runtime: Runtime[Context]) -> dict:
    tenant = runtime.context["tenant"]
    return {"path": [f"load({tenant})"]}


def answer(state: State, runtime: Runtime[Context]) -> dict:
    tenant = runtime.context["tenant"]
    budget = runtime.context["budget_tokens"]
    return {"path": [f"answer({tenant}, budget={budget})"],
            "answer": f"{tenant} 的答复"}


def build():
    g = StateGraph(State, context_schema=Context)
    g.add_node("load", load)
    g.add_node("answer", answer)
    g.add_edge(START, "load")
    g.add_edge("load", "answer")
    g.add_edge("answer", END)
    return g.compile()


def main() -> None:
    app = build()
    print("=== 1. 同一张图，两次运行传不同的 context ===")
    for tenant in ("tenant-a", "tenant-b"):
        out = app.invoke(
            {"answer": "", "path": []},
            context={"tenant": tenant, "budget_tokens": 8000},
        )
        print(f"  {tenant}: {out['answer']}  path={' / '.join(out['path'])}")
    print()

    print("=== 2. 试着把 context 塞进 state ===")
    out = app.invoke(
        {"answer": "", "path": [], "tenant": "tenant-c"},   # 多给的键
        context={"tenant": "tenant-a", "budget_tokens": 8000},
    )
    print(f"  返回的 state 键：{sorted(out)}")
    print("  <- 多给的 tenant 不在 State 里，被丢掉；它不会进入检查点")
    print()
    print("=== 3. 两者的分工 ===")
    print("  state：会产生检查点、会被 reducer 合并、恢复时要还原")
    print("  context：每次调用传入，不进检查点；租户、预算、权限、当前用户都属于它")


if __name__ == "__main__":
    main()
