"""五个装配预设：同一套组件，只改配置（v3 入口）。

运行：
    $env:PYTHONPATH="src"
    python examples/assembly.py
"""

from __future__ import annotations

import asyncio

from harness.assembly import build_harness
from harness.assembly.fpresets import (
    minimal,
    pe as pe_cfg,
    production,
    react as react_cfg,
    workflow as wf_cfg,
)
from harness.contracts.types import Goal, Plan, Step
from harness.fp import pe as pe_program, react as react_program, workflow as wf_program
from harness.parts.policy import ScriptedPlanner
from harness.parts.tools import tool
from demo_model import FakeModel, answer, tool_call


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


@tool
async def get_order(order_id: str) -> dict:
    """查询订单。"""
    return {"order_id": order_id, "status": "已签收"}


def _with_model(h, model):
    h.model = model
    return h


async def main() -> None:
    print("=== 1. minimal ===")
    h = build_harness(minimal(tools=(concat,)))
    r = await _with_model(h, FakeModel([answer("hello")])).run(
        react_program(max_steps=2), Goal("hi", session_id="min"))
    print(r.status, r.answer)

    print("=== 2. react ===")
    h = build_harness(react_cfg(tools=(concat,)))
    r = await _with_model(h, FakeModel([tool_call("concat", left="a", right="b"),
                                        answer("ab")])).run(
        react_program(max_steps=3), Goal("拼接", session_id="react"))
    print(r.status, r.answer)

    print("=== 3. workflow ===")
    h = build_harness(wf_cfg(tools=(concat,)))
    program = wf_program(
        Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
        Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
    )
    r = await _with_model(h, FakeModel([answer("unused")])).run(
        program, Goal("拼接", session_id="wf"))
    print(r.status, r.answer)

    print("=== 4. pe ===")
    h = build_harness(pe_cfg(tools=(concat,)))
    plan = Plan(id="p1", steps=[
        Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
        Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
    ])
    r = await _with_model(h, FakeModel([answer("unused")])).run(
        pe_program(ScriptedPlanner(plan), max_steps=3), Goal("拼接", session_id="pe"))
    print(r.status, r.answer)

    print("=== 5. production ===")
    h = build_harness(production(tools=(get_order,)))
    r = await _with_model(h, FakeModel([tool_call("get_order", order_id="A1001"),
                                        answer("已签收")])).run(
        react_program(max_steps=3), Goal("A1001 状态", session_id="prod"))
    print(r.status, r.answer, "guardrails=", len(h.guardrails))


if __name__ == "__main__":
    asyncio.run(main())
