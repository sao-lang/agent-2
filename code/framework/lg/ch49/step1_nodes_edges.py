"""第 49 章 step1：节点、边与条件边（离线）。

运行：
    python code/framework/lg/ch49/step1_nodes_edges.py

上一级的痛点：
    只会 START → A → END。真实流程要"按情况走不同路"。

这一级做什么：
    ① add_node 的三种参数（函数 / 带名字 / 带 retry_policy）
    ② add_edge（固定边）与 add_conditional_edges（条件边）
    ③ 条件边函数返回什么（节点名 vs 节点名列表 vs END）
    ④ 一个坑：条件边返回一个不存在的节点名
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
    question: str
    route: str
    answer: str
    trace: Annotated[list[str], lambda a, b: a + b]


def classify(state: S) -> dict:
    q = state["question"]
    if "退款" in q:
        r = "refund"
    elif "物流" in q:
        r = "logistics"
    elif "投诉" in q:
        r = "escalate"
    else:
        r = "unknown"
    return {"route": r, "trace": [f"classify→{r}"]}


def refund(state: S) -> dict:
    return {"answer": "退款 7 个工作日到账", "trace": ["refund"]}


def logistics(state: S) -> dict:
    return {"answer": "包裹已到驿站", "trace": ["logistics"]}


def escalate(state: S) -> dict:
    return {"answer": "已转人工，2 小时内联系您", "trace": ["escalate"]}


def fallback(state: S) -> dict:
    return {"answer": "没听懂，能再说一次吗？", "trace": ["fallback"]}


class S3(TypedDict):
    n: int
    trace: Annotated[list[str], lambda a, b: a + b]


def main() -> None:
    line("① 固定边 vs 条件边")
    print("""  add_edge("a", "b")               固定：a 完事必定去 b
  add_conditional_edges("a", f)    条件：a 完事调用 f(state)，由返回值决定去哪
                                    第三个参数是「返回值 → 节点名」的映射表（可选，但强烈建议）""")

    g = StateGraph(S)
    g.add_node("classify", classify)
    g.add_node("refund", refund)
    g.add_node("logistics", logistics)
    g.add_node("escalate", escalate)
    g.add_node("fallback", fallback)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        lambda s: s["route"],                      # 依据
        {                                          # 映射表：可枚举、可校验
            "refund": "refund",
            "logistics": "logistics",
            "escalate": "escalate",
            "unknown": "fallback",
        },
    )
    for n in ("refund", "logistics", "escalate", "fallback"):
        g.add_edge(n, END)

    app = g.compile()
    for q in ["我要退款", "物流呢", "我要投诉", "你们老板是谁"]:
        out = app.invoke({"question": q, "route": "", "answer": "", "trace": []})
        print(f"  {q:<10} → [{out['route']:<9}] {out['answer']}")

    line("② 条件边函数可以返回：节点名 / 节点名列表 / END")
    print("  ⚠️ 注意：router 的**类型注解**会在运行时被求值（get_type_hints），")
    print("     所以别给它标注定义在函数内的 TypedDict —— 会 NameError。真实项目把 schema 放模块级。")

    def step2(_s: S3) -> dict:
        return {"n": _s["n"] + 1, "trace": [f"step({_s['n']})"]}

    def router2(s: S3) -> str:
        return "step" if s["n"] < 3 else END

    g2 = StateGraph(S3)
    g2.add_node("step", step2)
    g2.add_edge(START, "step")
    g2.add_conditional_edges("step", router2)
    out2 = g2.compile().invoke({"n": 0, "trace": []})
    print(f"\n  循环 3 次 → n={out2['n']}，trace={out2['trace']}")
    print("  → 条件边返回 END 就是「结束」；这一步构成 while 循环（第 16 章的步数上限要自己加）")

    line("③ 一个坑：条件边返回了不存在的节点名")
    g3 = StateGraph(S)
    g3.add_node("classify", classify)
    g3.add_node("refund", refund)
    g3.add_edge(START, "classify")
    g3.add_conditional_edges("classify", lambda s: s["route"], {"refund": "refund"})
    g3.add_edge("refund", END)
    try:
        g3.compile().invoke({"question": "物流呢", "route": "", "answer": "", "trace": []})
    except Exception as e:  # noqa: BLE001
        print(f"  → {type(e).__name__}: {str(e).splitlines()[0][:130]}")
    print("  → 映射表里漏掉一个键，就是一个线上 500。所以映射表要和 classify 的返回值同步维护。")

    line("④ 节点也能带重试策略")
    print("  g.add_node('classify', classify, retry_policy=RetryPolicy(max_attempts=3))")
    print("  → 稳定且快的节点（分类）值得加；有副作用的节点（发邮件）要谨慎：重试 = 可能发两封（见 48.6）")


if __name__ == "__main__":
    main()
