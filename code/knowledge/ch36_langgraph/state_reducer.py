"""LangGraph 的状态与 reducer：同一个字段被两个节点写，会发生什么。

不联网。三个实验：
  1. 顺序写同一个 list：有 reducer 时是追加，没有 reducer 时是覆盖
  2. 并行写同一个 str：没有 reducer 直接报 InvalidUpdateError
  3. 自定义 reducer：去重 + 计数，处理第 35 章那种"两个分支都看到"的情况

运行：python code/knowledge/ch36_langgraph/state_reducer.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.errors import InvalidUpdateError
from langgraph.graph import END, START, StateGraph


class AppendState(TypedDict):
    log: Annotated[list[str], operator.add]


class PlainState(TypedDict):
    log: list[str]


class VerdictState(TypedDict):
    verdict: str


class FindingState(TypedDict):
    findings: Annotated[list[str], dedupe]
    votes: Annotated[dict[str, int], count_votes]


def dedupe(left: list[str], right: list[str]) -> list[str]:
    """自定义 reducer：按出现顺序合并，同一个发现只留一条。"""
    out = list(left)
    for item in right:
        if item not in out:
            out.append(item)
    return out


def count_votes(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    out = dict(left)
    for key, n in right.items():
        out[key] = out.get(key, 0) + n
    return out


def append_a(state: AppendState) -> dict:
    return {"log": ["a"]}


def append_b(state: AppendState) -> dict:
    return {"log": ["b"]}


def plain_a(state: PlainState) -> dict:
    return {"log": ["a"]}


def plain_b(state: PlainState) -> dict:
    return {"log": ["b"]}


def verdict_a(state: VerdictState) -> dict:
    return {"verdict": "a"}


def verdict_b(state: VerdictState) -> dict:
    return {"verdict": "b"}


def branch_a(state: FindingState) -> dict:
    return {"findings": ["连接池耗尽", "重试无上限"],
            "votes": {"连接池耗尽": 1, "重试无上限": 1}}


def branch_b(state: FindingState) -> dict:
    return {"findings": ["连接池耗尽", "超时为零"],
            "votes": {"连接池耗尽": 1, "超时为零": 1}}


def build(state_cls, nodes, edges) -> object:
    g = StateGraph(state_cls)
    for name, fn in nodes:
        g.add_node(name, fn)
    for src, dst in edges:
        g.add_edge(src, dst)
    return g.compile()


def main() -> None:
    print("=== 1. 顺序写 list：有 reducer vs 没有 ===")
    app = build(AppendState, [("a", append_a), ("b", append_b)],
                [(START, "a"), ("a", "b"), ("b", END)])
    print(f"  Annotated[list, operator.add] -> {app.invoke({'log': []})}")

    app = build(PlainState, [("a", plain_a), ("b", plain_b)],
                [(START, "a"), ("a", "b"), ("b", END)])
    print(f"  普通 list                      -> {app.invoke({'log': []})}")
    print("  <- 没有 reducer 时后写覆盖前写，前一个节点的输出直接消失")
    print()

    print("=== 2. 并行写同一个 str：没有 reducer ===")
    app = build(VerdictState, [("a", verdict_a), ("b", verdict_b)],
                [(START, "a"), (START, "b"), ("a", END), ("b", END)])
    try:
        app.invoke({"verdict": ""})
    except InvalidUpdateError as e:
        first = str(e).splitlines()[0]
        print(f"  {type(e).__name__}: {first}")
    print("  <- 框架在超步结束时发现两个值，直接拒绝，不替你选一个")
    print()

    print("=== 3. 自定义 reducer：去重 + 计数 ===")
    app = build(FindingState, [("a", branch_a), ("b", branch_b)],
                [(START, "a"), (START, "b"), ("a", END), ("b", END)])
    out = app.invoke({"findings": [], "votes": {}})
    print(f"  findings={out['findings']}")
    print(f"  votes={out['votes']}")
    print("  <- 两条分支都报到的'连接池耗尽'计数为 2，这是列表去重会丢的信息")


if __name__ == "__main__":
    main()
