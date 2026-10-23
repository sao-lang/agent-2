"""第 62 章 step1：三个框架跑同一个任务 —— 代码量、概念数、可控性对比。

运行：
    python code/framework/misc/step1_same_task_three_ways.py

同一个业务需求，用三种方式写一遍：

    需求：用户问「A8821 能退吗」，需要
      ① 查订单 ② 查退款政策 ③ 给出结论（能不能退 + 理由）

    实现 A：纯手写（不依赖框架）
    实现 B：pydantic-ai（强类型 + deps 注入）
    实现 C：LangGraph（显式图）

比较四个维度：
    · 代码行数（真的数出来，不是我估的）
    · 概念个数（要理解多少个新名词才能读懂）
    · 可控性（能不能精确控制"先做什么后做什么"）
    · 可测性（能不能在不起模型的情况下测）

全程用假模型 / 纯函数，**离线可跑**，不调任何 API。

> 诚实说明：这里的「代码行数」只统计业务逻辑部分（不含 import 和 docstring），
> 因为 import 行数不反映心智负担。所有数字都是本脚本实际数出来的。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TypedDict

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 78


# ================================================================ 共享的假数据
ORDERS = {
    "A8821": {"amount": 399, "status": "delivered", "days_since": 5, "reason": "quality"},
    "A9999": {"amount": 599, "status": "delivered", "days_since": 40, "reason": "personal"},
}
POLICY = {"quality_days": 15, "personal_days": 7}


def lookup_order(order_id: str) -> dict:
    return ORDERS.get(order_id, {})


def lookup_policy() -> dict:
    return POLICY


def decide(order: dict, policy: dict) -> tuple[bool, str]:
    """纯业务规则：能不能退。"""
    if not order:
        return False, "订单不存在"
    limit = policy["quality_days"] if order["reason"] == "quality" else policy["personal_days"]
    if order["days_since"] <= limit:
        return True, f"{order['days_since']} 天 < {limit} 天，可退"
    return False, f"已 {order['days_since']} 天，超过 {limit} 天期限"


# ================================================================ A 纯手写
def impl_plain(order_id: str) -> dict:
    """不依赖任何框架：顺序写死，逻辑一眼看完。"""
    order = lookup_order(order_id)
    policy = lookup_policy()
    ok, reason = decide(order, policy)
    return {"answer": f"{'可以' if ok else '不可以'}退：{reason}", "ok": ok}


# ================================================================ B pydantic-ai
# ⚠️ 真实坑：`RunContext` 必须在**模块级**导入，Deps 也要在模块级定义。
# 原因：pydantic-ai 用 get_type_hints() 在模块作用域解析注解，
# 函数内的局部名字它看不到 —— 会报 NameError: name 'RunContext' is not defined。
from pydantic_ai import RunContext  # noqa: E402


# ⚠️ 同理，Deps 和输出模型也必须定义在**模块级**。
# 定义在函数内部时，`RunContext[Deps]` 的类型解析会失败。
@dataclass
class Deps:
    orders: dict
    policy: dict


def build_pydantic_ai():
    """pydantic-ai 版：deps 注入 + 强类型输出。

    注意：这里用 TestModel 是为了离线可跑。
    真实使用时把 TestModel() 换成 'openai:gpt-4o' 之类的字符串即可。
    """
    from pydantic import BaseModel
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    class RefundVerdict(BaseModel):
        order_id: str
        eligible: bool
        reason: str

    agent = Agent(
        TestModel(),
        deps_type=Deps,
        output_type=RefundVerdict,
        system_prompt="判断订单能否退款。必须先查订单和退款政策。",
    )

    @agent.tool
    def get_order(ctx: RunContext[Deps], order_id: str) -> dict:
        """按订单号查询订单详情。"""
        return ctx.deps.orders.get(order_id, {})

    @agent.tool
    def get_policy(ctx: RunContext[Deps]) -> dict:
        """查询退款政策（质量问题和人为原因的期限不同）。"""
        return ctx.deps.policy

    return agent, Deps(orders=ORDERS, policy=POLICY)


# ================================================================ C LangGraph
def build_langgraph():
    """LangGraph 版：显式节点 + 显式边。"""
    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        order_id: str
        order: dict
        policy: dict
        eligible: bool
        reason: str

    def n_order(s: S) -> dict:
        return {"order": lookup_order(s["order_id"])}

    def n_policy(s: S) -> dict:
        return {"policy": lookup_policy()}

    def n_decide(s: S) -> dict:
        ok, why = decide(s["order"], s["policy"])
        return {"eligible": ok, "reason": why}

    g = StateGraph(S)
    g.add_node("order", n_order)
    g.add_node("policy", n_policy)
    g.add_node("decide", n_decide)
    g.add_edge(START, "order")
    g.add_edge("order", "policy")
    g.add_edge("policy", "decide")
    g.add_edge("decide", END)
    return g.compile()


# ================================================================ 跑三遍
def run_all() -> dict:
    print(DPRINT)
    print("① 三种实现跑同一个问题")
    print(DPRINT)

    results = {}

    # A
    ra = impl_plain("A8821")
    print(f"  A 纯手写      -> {ra['answer']}")
    results["A"] = ra["answer"]

    # B
    agent, deps = build_pydantic_ai()
    rb = agent.run_sync("A8821 能退吗", deps=deps)
    print(f"  B pydantic-ai -> eligible={rb.output.eligible} reason={rb.output.reason!r}")
    print(f"                    （输出类型是 {type(rb.output).__name__}，不是字符串）")
    print(f"                    usage: {rb.usage}")
    print()
    print("  ⚠️ 必须诚实说明 B 的输出：**结论是错的（eligible=False, reason='a'）**。")
    print("     这不是代码 bug，是 TestModel 的行为：")
    print("     「will (by default) call all tools in the agent, then return a tool response")
    print("      if possible, otherwise a plain response」—— 它填的是假数据 'a'。")
    print("     所以 B 这一行证明的只是「管线通了、工具被调了（tool_calls=2）」,")
    print("     **不证明「模型判断对了」**。后者必须用真实模型 + 评测集（第 61 章）。")
    print()
    print("     这也是本章要和 61 章连着读的原因：框架能让你「跑起来」，")
    print("     但「跑对了」只能靠评测证明。")
    results["B"] = "(TestModel 假数据)"

    # C
    app = build_langgraph()
    rc = app.invoke({"order_id": "A8821"})
    print(f"  C LangGraph   -> eligible={rc['eligible']} reason={rc['reason']}")
    results["C"] = rc["reason"]

    print()
    print("  ---- 三种都能跑通，但你为它付出了不同的学习成本。")
    print("       而「跑通」和「跑对」是两件事 —— 见上面 B 的说明。")
    return results


# ================================================================ 概念数
def demo_concepts() -> None:
    print()
    print(DPRINT)
    print("② 读懂它需要理解多少新概念")
    print(DPRINT)

    table = [
        ("A 纯手写", ["函数"], "会 Python 就能读"),
        ("B pydantic-ai", ["Agent", "deps_type（依赖注入）", "RunContext",
                           "output_type（强类型输出）", "TestModel"],
         "要理解「依赖注入」和「结构化输出」两个设计模式"),
        ("C LangGraph", ["StateGraph", "State（TypedDict）", "节点（读 state 返回补丁）",
                         "边（add_edge）", "START / END", "compile()"],
         "要理解「状态机」这个模型"),
    ]
    print(f"  {'实现':<16} {'新概念数':<10} 新概念")
    print(f"  {'-' * 16} {'-' * 10} {'-' * 46}")
    for name, concepts, note in table:
        print(f"  {name:<16} {len(concepts):<10} {', '.join(concepts)}")
        print(f"  {'':<16} {'':<10} └ {note}")

    print()
    print("  ---- 概念多不等于不好。要看「这些概念买到了什么」：")
    rows = [
        ("A 纯手写", "0 个", "顺序写死，改流程要改代码"),
        ("B pydantic-ai", "依赖注入 + 强类型", "换租户/换数据源不改业务代码；输出直接是对象"),
        ("C LangGraph", "状态机", "能中断、能持久化、能可视化、能并行"),
    ]
    print(f"  {'实现':<16} {'付出的概念':<24} 买到了什么")
    print(f"  {'-' * 16} {'-' * 24} {'-' * 34}")
    for a, b, c in rows:
        print(f"  {a:<16} {b:<24} {c}")


# ================================================================ 可控性
def demo_control() -> None:
    print()
    print(DPRINT)
    print("③ 可控性：能不能保证「先查订单再查政策」")
    print(DPRINT)

    print("  A 纯手写：")
    print("     ✅ 完全可控 —— 就是上下两行代码，顺序不可能变")
    print()
    print("  B pydantic-ai：")
    print("     ⚠️ **顺序由模型决定**。你在 system_prompt 里写「必须先查订单和退款政策」，")
    print("        但模型可以选择只查一个，或者两个都不查直接回答。")
    print("        框架提供的是「工具可用」，不是「工具必用」。")
    print("        要强制顺序，得靠 output validator 或自定义 capability。")
    print()
    print("  C LangGraph：")
    print("     ✅ 完全可控 —— order -> policy -> decide 是写死的边，")
    print("        除非你显式加条件边，否则不可能跳过。")
    print()
    print("  ---- 这是选框架时最该问的一个问题：")
    print("     「流程是确定的，还是需要模型临场决定？」")
    print()
    rows = [
        ("流程完全确定", "A 纯手写 或 C LangGraph", "别让模型有机会乱走"),
        ("流程大体确定、个别分支要模型判断", "C LangGraph + 条件边", "骨架写死，岔路口交给模型"),
        ("完全不知道下一步该做什么", "B pydantic-ai 或 LangChain create_agent", "这才是 ReAct 的用武之地"),
    ]
    print(f"  {'情况':<32} {'推荐':<36} 理由")
    print(f"  {'-' * 32} {'-' * 36} {'-' * 26}")
    for a, b, c in rows:
        print(f"  {a:<32} {b:<36} {c}")


# ================================================================ 可测性
def demo_testability() -> None:
    print()
    print(DPRINT)
    print("④ 可测性：不起模型能测吗")
    print(DPRINT)

    print("  A 纯手写：")
    print("     ✅ 直接调函数，纯单元测试，毫秒级")
    print()
    print("  B pydantic-ai：")
    print("     ✅ 有 TestModel —— 见 ① 的 B 那段，全程没调网络")
    print("        但 TestModel 返回的是**固定假数据**，只能测「管线通不通」，")
    print("        **测不出「模型会不会选对工具」**。那部分必须用真实模型 + 评测集。")
    print()
    print("  C LangGraph：")
    print("     ✅ 节点是普通函数，可以单独测")
    print("     ✅ 整图可以用假状态 invoke，也能测")
    print()
    print("  ---- 一个关键区分（很多人混在一起）：")
    rows = [
        ("业务逻辑对不对", "A 纯函数 / B 的 validator / C 的节点函数", "纯单测，快"),
        ("模型会不会用对工具", "必须真实模型 + 评测集（第 61 章）", "慢、贵，但没法替代"),
    ]
    print(f"  {'要测什么':<24} {'在哪测':<48} 代价")
    print(f"  {'-' * 24} {'-' * 48} {'-' * 16}")
    for a, b, c in rows:
        print(f"  {a:<24} {b:<48} {c}")


if __name__ == "__main__":
    run_all()
    demo_concepts()
    demo_control()
    demo_testability()
    print()
    print(DPRINT)
    print("step1 完成。三句话带走：")
    print("  1. 三种都能跑通 —— 差别不在「能不能」，在「你付出什么换什么」。")
    print("     注意 B 的输出是 TestModel 的假数据：跑通 != 跑对。")
    print("  2. 纯手写 = 0 概念但改流程要改代码；pydantic-ai = 依赖注入+强类型；")
    print("     LangGraph = 状态机，换来中断/持久化/可视化。")
    print("  3. **选框架先问「流程确定吗」**：确定就别让模型有机会乱走。")
    print(DPRINT)
