"""第 47 章 step2：图在运行时怎么推进（离线）。

运行：
    python code/framework/lg/ch47/step2_how_graph_runs.py

上一级的痛点：
    加了 reducer 之后图能跑了，但你不知道为什么"先算哪个"。
    改一条边，行为完全变了，却说不清原因。

这一级做什么：
    ① Superstep（超级步）：一轮里有哪几个节点会被同时执行
    ② 用 stream_mode="updates" 看见每一轮到底执行了什么
    ③ 入口点的三种写法 + set_node_defaults
    ④ 一个坑：忘了编译就调用（Pregel 才能跑）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

sys.path.insert(0, str(Path(__file__).parent))


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


class S(TypedDict):
    log: Annotated[list[str], lambda a, b: a + b]


def main() -> None:
    line("① 一轮里能同时跑几个节点：看边")
    def make(name: str):
        def node(_s: S) -> dict:
            return {"log": [name]}
        return node

    g = StateGraph(S)
    for n in ["a", "b", "c", "d"]:
        g.add_node(n, make(n))
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("a", "c")     # b 和 c 是并行分支
    g.add_edge(["b", "c"], "d")   # d 要等 b、c 都完成（列表边）
    g.add_edge("d", END)
    app = g.compile()

    print("  边：START→a, a→b, a→c, [b,c]→d, d→END")
    print("  逐轮观察（stream_mode='updates' 逐 chunk 打印）：")
    for i, chunk in enumerate(app.stream({"log": []}, stream_mode="updates"), 1):
        print(f"    chunk {i}: {list(chunk)}")
    print("\n  真实输出里 b 和 c 会各占一个 chunk —— 这不是「两轮」，是同一 superstep 的两个 task")
    print("  想确认分轮，用 stream_mode='debug' 看每条的 step 编号；")
    print("  想真正并行，节点要写成 async（同步节点串行执行）")

    line("② 一轮内并行 ≠ 线程并行")
    print("  · 同一 superstep 里的节点会被并发调度（同步用线程池，异步用事件循环）")
    print("  · 所以节点函数里**不要共享可变全局状态**")
    print("  · 结果是这一轮结束时**统一 merge** 进 state，这才需要 reducer")

    line("③ 入口点的三种写法")
    g2 = StateGraph(S)
    g2.add_node("x", make("x"))
    g2.add_edge(START, "x")          # 写法 1：显式 START 边（推荐，一眼看懂）
    g2.add_edge("x", END)
    print(f"  写法 1 add_edge(START, 'x')  → {g2.compile().invoke({'log': []})}")

    # 写法 2：set_entry_point（等价，但边的方向不直观）
    g3 = StateGraph(S)
    g3.add_node("x", make("x"))
    g3.set_entry_point("x")
    g3.add_edge("x", END)
    print(f"  写法 2 set_entry_point('x') → {g3.compile().invoke({'log': []})}")

    # 写法 3：add_sequence（只负责"顺次连边"，入口还要自己指）
    g4 = StateGraph(S)
    g4.add_sequence([("a", make("a")), ("b", make("b"))])
    g4.add_edge(START, "a")
    g4.add_edge("b", END)
    print(f"  写法 3 add_sequence        → {g4.compile().invoke({'log': []})}")
    print("     注意：add_sequence 不建入口/出口边，START 和 END 仍要自己连")

    line("④ RetryPolicy：节点失败自动重试（不用手写 try/except 循环）")
    from langgraph.types import RetryPolicy

    attempts = {"n": 0}

    def flaky(_s: S) -> dict:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError(f"第 {attempts['n']} 次连接失败")
        return {"log": [f"第 {attempts['n']} 次成功"]}

    g5 = StateGraph(S)
    g5.add_node(
        "flaky",
        flaky,
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.01, retry_on=ConnectionError),
    )
    g5.add_edge(START, "flaky")
    g5.add_edge("flaky", END)
    print(f"  结果 = {g5.compile().invoke({'log': []})['log']}，共尝试 {attempts['n']} 次")

    # 不加重试时会发生什么
    attempts["n"] = 0
    g6 = StateGraph(S)
    g6.add_node("flaky", flaky)
    g6.add_edge(START, "flaky")
    g6.add_edge("flaky", END)
    try:
        g6.compile().invoke({"log": []})
    except ConnectionError as e:
        print(f"  不加重试 → 直接抛出 {type(e).__name__}: {e}")
    print("  → retry_on 写**异常类**，不是字符串；只重试你声明的那几类（别把逻辑错误也重试）")

    line("⑤ 一个坑：不 compile 就没法 invoke")
    raw = StateGraph(S)
    raw.add_node("x", make("x"))
    raw.add_edge(START, "x")
    raw.add_edge("x", END)
    print(f"  StateGraph 实例有 invoke 吗？{hasattr(raw, 'invoke')}")
    print(f"  compile() 之后有吗？        {hasattr(raw.compile(), 'invoke')}")
    print("  → StateGraph 是「图纸」，compile() 才生成可执行的 Pregel 引擎")


if __name__ == "__main__":
    main()
