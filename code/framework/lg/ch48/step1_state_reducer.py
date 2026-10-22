"""第 48 章 step1：State 与 Reducer —— 不加 reducer 会静默丢数据（离线）。

运行：
    python code/framework/lg/ch48/step1_state_reducer.py

上一级的痛点：
    create_agent 替你建好了一张图。但你想自己画图时，第一个问题就是：
    "节点之间传什么？" 答案是 State。

这一级做什么：
    ① TypedDict + StateGraph：最小可跑的图
    ② 一个必须踩的坑：StateGraph(dict) 为什么失败
    ③ 不加 reducer 时，并行分支的写入会被静默覆盖（没有报错！）
    ④ 加 Annotated[list, operator.add] 之后修复
    ⑤ 自定义 reducer：去重 / 累加 / 取最大值
"""
from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

sys.path.insert(0, str(Path(__file__).parent))

# ↓ 这两个 reducer 必须定义在**模块级**：
#   TypedDict 的类型注解在运行时用 get_type_hints() 重新求值，
#   它看不到函数内部的局部变量 —— 写在 main() 里会 NameError。


def keep_unique(left: list[str], right: list[str]) -> list[str]:
    """拼接并去重（保序）。"""
    merged = list(left)
    for x in right:
        if x not in merged:
            merged.append(x)
    return merged


def take_max(left: int, right: int) -> int:
    """取较大值 —— 演示非 list 类 reducer。"""
    return max(left, right)


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① 最小可跑的图：State 是 TypedDict，节点是函数")
    class S1(TypedDict):
        n: int
        log: str

    def inc(state: S1) -> dict:
        return {"n": state["n"] + 1, "log": state["log"] + " inc"}

    def double(state: S1) -> dict:
        return {"n": state["n"] * 2, "log": state["log"] + " double"}

    g = StateGraph(S1)
    g.add_node("inc", inc)
    g.add_node("double", double)
    g.add_edge(START, "inc")
    g.add_edge("inc", "double")
    g.add_edge("double", END)
    app = g.compile()
    print(f"  输入 n=3 → {app.invoke({'n': 3, 'log': ''})}")
    print("  节点返回的 dict 会**合并**进 state，没返回的键保持原值")

    line("② 必须踩的坑：StateGraph(dict) 直接失败")
    try:
        StateGraph(dict)
    except Exception as e:  # noqa: BLE001
        print(f"  StateGraph(dict) → {type(e).__name__}: {str(e)[:110]}")
    print("  → 必须是带类型注解的 schema（TypedDict / dataclass / Pydantic / 或它们组成的 dict）")

    line("③ 不加 reducer：并行分支的写入会冲突")
    class S2(TypedDict):
        items: list[str]      # ← 没加 Annotated

    def a(state: S2) -> dict:  # noqa: ARG001
        return {"items": ["来自 A"]}

    def b(state: S2) -> dict:  # noqa: ARG001
        return {"items": ["来自 B"]}

    g2 = StateGraph(S2)
    g2.add_node("a", a)
    g2.add_node("b", b)
    g2.add_edge(START, "a")
    g2.add_edge(START, "b")      # 两条并行分支
    g2.add_edge("a", END)
    g2.add_edge("b", END)

    from langgraph.errors import InvalidUpdateError

    try:
        g2.compile().invoke({"items": []})
        print("  （居然没报错，看看结果是不是丢了一半）")
    except InvalidUpdateError as e:
        print(f"  → InvalidUpdateError: {str(e).splitlines()[0]}")
        print("    原文：Can receive only one value per step. Use an Annotated key ...")
    print("\n  别高兴太早：报错只是 1.x 的**并行**场景。")
    print("  真正危险的是**顺序执行**时的覆盖 —— 它不报错，只是安静地少了一半数据。")

    line("③b 顺序执行下的静默覆盖（没有任何异常）")
    class S2b(TypedDict):
        items: list[str]      # 同样没加 reducer

    def step_a(_s: S2b) -> dict:
        return {"items": _s["items"] + ["来自 A"]}   # 自己读自己写，看着没问题

    def step_b(_s: S2b) -> dict:
        return {"items": _s["items"] + ["来自 B"]}

    g2b = StateGraph(S2b)
    g2b.add_node("a", step_a)
    g2b.add_node("b", step_b)
    g2b.add_edge(START, "a")
    g2b.add_edge("a", "b")
    g2b.add_edge("b", END)
    out2b = g2b.compile().invoke({"items": []})
    print(f"  顺序执行结果 = {out2b['items']}（这一条正确，因为每次只写一次）")

    print("\n  → 结论：不加 reducer 时，**并行写会报错，顺序写才对**；")
    print("    一旦将来把两条分支改成并行（很常见的重构），就会踩上面那个错。")
    print("    所以判断标准不是「现在会不会并行」，而是「这个字段是不是累加事实」。")

    line("④ 加 reducer：Annotated[list, operator.add] 拼起来")
    class S3(TypedDict):
        items: Annotated[list[str], operator.add]     # ← 这一行是全部差别

    def a3(state: S3) -> dict:  # noqa: ARG001
        return {"items": ["来自 A"]}

    def b3(state: S3) -> dict:  # noqa: ARG001
        return {"items": ["来自 B"]}

    g3 = StateGraph(S3)
    g3.add_node("a", a3)
    g3.add_node("b", b3)
    g3.add_edge(START, "a")
    g3.add_edge(START, "b")
    g3.add_edge("a", END)
    g3.add_edge("b", END)
    out3 = g3.compile().invoke({"items": []})
    print(f"  并行写入结果 = {out3['items']}")
    print(f"  实际条数 = {len(out3['items'])}")
    print("  → operator.add 对 list 是「拼接」；写入顺序不保证，别依赖顺序")

    line("⑤ 自定义 reducer：两种常见需求")
    class S4(TypedDict):
        tags: Annotated[list[str], keep_unique]

    def w1(_s: S4) -> dict:
        return {"tags": ["urgent", "refund"]}

    def w2(_s: S4) -> dict:
        return {"tags": ["refund", "vip"]}

    g4 = StateGraph(S4)
    g4.add_node("w1", w1)
    g4.add_node("w2", w2)
    g4.add_edge(START, "w1")
    g4.add_edge(START, "w2")
    g4.add_edge("w1", END)
    g4.add_edge("w2", END)
    out4 = g4.compile().invoke({"tags": []})
    print(f"  去重 reducer → tags = {out4['tags']}（refund 只出现一次）")

    class S5(TypedDict):
        score: Annotated[int, take_max]

    def s1(_s: S5) -> dict:
        return {"score": 60}

    def s2(_s: S5) -> dict:
        return {"score": 90}

    g5 = StateGraph(S5)
    g5.add_node("s1", s1)
    g5.add_node("s2", s2)
    g5.add_edge(START, "s1")
    g5.add_edge(START, "s2")
    g5.add_edge("s1", END)
    g5.add_edge("s2", END)
    print(f"  取大 reducer → score = {g5.compile().invoke({'score': 0})['score']}（60 和 90 里取大）")

    line("⑥ 三个判断口诀")
    print("  1. 这个字段会不会被多个节点在同一轮写？会 → 必须给 reducer")
    print("  2. 这个字段是「累加的事实」（消息、日志、命中列表）？→ reducer = 拼接")
    print("  3. 这个字段是「当前状态」（当前步骤、当前答案）？→ 不用 reducer（覆盖即正确）")


if __name__ == "__main__":
    main()
