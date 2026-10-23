"""第 44 章 step3：两种形态 + 三个最容易写错的坑（离线，真 LangGraph）。

运行：
    python code/ch37_multi_agent/step3_shapes.py

上一级的痛点：判据说"可以拆"，但拆出来的图长什么样？

这一级做什么：用 langgraph 真跑两种形态，并且**故意踩三个坑**给你看：
  坑 1  `Send` 的第二个参数传裸值      → worker 收到空状态
  坑 2  `results` 不加 reducer          → 三个分支只剩一个，且不报错
  坑 3  Supervisor 转述子 Agent 全文     → 协调者上下文线性膨胀

坑 1/2 的"错法"用最小图单独演示，不污染正确实现。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Send  # noqa: E402

from langgraph.errors import InvalidUpdateError  # noqa: E402

from common.multi_agent import build_fan, build_supervisor  # noqa: E402

# ---------------------------------------------------------------- 坑 1/2


class BadState(TypedDict, total=False):
    task: str
    subtasks: list[str]
    results: list[str]          # ⚠️ 故意不加 Annotated[..., merge]


def bad_fan_out(state: BadState) -> list:
    # ⚠️ 故意传裸值而不是完整 state 字典
    return [Send("worker", s) for s in state.get("subtasks", [])]


def bad_worker(state) -> dict:
    # worker 以为自己在处理 state 字典，但 Send 传的是裸字符串 A / B / C
    return {"results": [f"完成：{state['sub']}"]}


def bad_join(state: BadState) -> dict:
    return {}


def build_bad_send_only():
    """只坑 1：Send 传裸值，但 results 有 reducer（三个分支能同时写）。"""
    g = StateGraph(GoodState)
    g.add_node("plan", lambda s: {"subtasks": ["A", "B", "C"]})
    g.add_node("worker", bad_worker)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", bad_fan_out, ["worker"])
    g.add_edge("worker", END)
    return g.compile()


def build_bad_no_reducer():
    """只坑 2：results 不加 reducer（Send 是对的）。"""
    g = StateGraph(BadState)
    g.add_node("plan", lambda s: {"subtasks": ["A", "B", "C"]})
    g.add_node("worker", good_worker)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", good_fan_out, ["worker"])
    g.add_edge("worker", END)
    return g.compile()


# 正确的工人（Send 传完整 state，results 用 reducer 累加）
def _merge(left: list, right: list) -> list:
    return (left or []) + (right or [])


class GoodState(TypedDict, total=False):
    task: str
    subtasks: list[str]
    results: Annotated[list[str], _merge]


def good_fan_out(state) -> list:
    return [Send("worker", {"task": state.get("task", ""), "sub": s}) for s in state.get("subtasks", [])]


def good_worker(state: dict) -> dict:
    return {"results": [f"完成：{state['sub']}"]}


def build_good():
    g = StateGraph(GoodState)
    g.add_node("plan", lambda s: {"subtasks": ["A", "B", "C"]})
    g.add_node("worker", good_worker)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", good_fan_out, ["worker"])
    g.add_edge("worker", END)
    return g.compile()


def main() -> None:
    print("=" * 78)
    print("坑 1 + 坑 2：Send 传裸值 + results 不加 reducer")
    print("=" * 78)
    for label, graph in (("坑 1（Send 传裸值）", build_bad_send_only()),
                         ("坑 2（不写 reducer）", build_bad_no_reducer())):
        print(f"\n  【{label}】")
        try:
            out = graph.invoke({"task": "写三份文案"})
            print(f"    结果条数：{len(out.get('results', []))}（期望 3）")
            for r in out.get("results", []):
                print(f"      {r}")
        except (InvalidUpdateError, AttributeError, TypeError) as exc:
            print(f"    ❌ 抛错：{type(exc).__name__}: {str(exc).splitlines()[0][:90]}")
    print("\n  👉 好消息：这两个坑在 langgraph 1.x 上都会**当场抛错**，不会静默丢数据。")
    print("     （0.x 时代的'不写 reducer 就静默覆盖、还不报错'已经修掉了——")
    print("      老教程里的警告仍然要记，但你现在有 CI 兜底。）")
    print("     坏消息：报错信息只说'results 只能收一个值'，")
    print("     不会告诉你是哪个分支写错了。所以还是要自己知道该看哪里。")

    print("\n" + "=" * 78)
    print("修法：Send 传完整 state + Annotated reducer")
    print("=" * 78)
    out = build_good().invoke({"task": "写三份文案"})
    print(f"  结果条数：{len(out.get('results', []))}（期望 3）")
    for r in out.get("results", []):
        print(f"    {r}")

    print("\n" + "=" * 78)
    print("形态 A：Supervisor（协调者分派，串行）")
    print("=" * 78)
    app = build_supervisor()
    t0 = time.perf_counter()
    out = app.invoke({"task": "调研竞品", "findings": [], "rounds": 0})
    sup_ms = (time.perf_counter() - t0) * 1000
    print(f"  轮次：{out.get('rounds')}")
    for f in out.get("findings", []):
        print(f"    {f}")
    print(f"  耗时：{sup_ms:.0f}ms")
    print("\n  👉 串行：每个 worker 都要等前一个。")
    print("     只有当'后一个必须看前一个的结果'时，这种形态才是对的。")

    print("\n" + "=" * 78)
    print("形态 B：并行 fan-out（延迟取 max）")
    print("=" * 78)
    fan = build_fan()
    t0 = time.perf_counter()
    out = fan.invoke({"task": "写三份文案", "subtasks": [], "results": []})
    fan_ms = (time.perf_counter() - t0) * 1000
    print(f"  结果：{out.get('final')}")
    print(f"  子结果数：{len(out.get('results', []))}")
    print(f"  耗时：{fan_ms:.0f}ms")
    print("\n  👉 这是多 Agent 唯一无可替代的收益：墙钟时间从 sum 变 max。")

    print("\n" + "=" * 78)
    print("坑 3：Supervisor 转述子 Agent 全文 → 协调者上下文线性膨胀")
    print("=" * 78)
    print(f"  {'轮次':>4}{'协调者累计读入(字)':>22}{'占总上下文':>12}")
    print("  " + "-" * 40)
    payload = 400          # 假设每个子 Agent 输出 400 字
    total = 0
    for r in range(1, 6):
        total += payload * r          # 第 r 轮要把前面所有输出都转述一遍
        print(f"  {r:>4}{total:>22,}{total / (total + 800):>11.0%}")
    print("\n  👉 5 轮之后协调者要读 6,000 字，而子 Agent 各自只产出 400 字。")
    print("     正确做法：子 Agent 直接写共享黑板，协调者只读**摘要**，不搬正文。")

    print("\n" + "=" * 78)
    print("三种形态的取舍（一句话版）")
    print("=" * 78)
    print("  · 能并行      → fan-out（唯一省时间）")
    print("  · 必须串行看  → Supervisor，且协调者只搬摘要")
    print("  · 只是想分工  → 不拆，单 Agent + 更细的 prompt")


if __name__ == "__main__":
    main()
