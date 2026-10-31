"""五个装配预设：同一套组件，只改配置。

运行：
    $env:PYTHONPATH="code/harness/src"
    python code/harness/examples/assembly.py
"""

from __future__ import annotations

import asyncio

from harness import (
    AllowAllGuard,
    AutoRetrieval,
    Budget,
    Goal,
    InMemoryKnowledge,
    MemoryDurability,
    MemoryTracer,
    Plan,
    Recalled,
    ScriptedPlanner,
    Step,
    build_minimal,
    build_pe,
    build_production,
    build_react,
    build_workflow,
    tool,
)
from harness.testing import FakeModel, answer, tool_call


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


@tool
async def get_order(order_id: str) -> dict:
    """查询订单。"""
    return {"order_id": order_id, "status": "已签收"}


async def main() -> None:
    print("=== 1. minimal ===")
    a = build_minimal(model=FakeModel([answer("hello")]))
    r = await a.run(Goal("hi", session_id="min"))
    print(r.status, r.answer)

    print("=== 2. react ===")
    a = build_react(
        model=FakeModel([tool_call("concat", left="a", right="b"), answer("ab")]),
        tools=[concat],
        budget=Budget(tokens=1000, calls=4),
    )
    r = await a.run(Goal("拼接", session_id="react"))
    print(r.status, r.answer)

    print("=== 3. workflow ===")
    a = build_workflow(
        model=FakeModel([answer("unused")]),
        tools=[concat],
        workflow=[
            Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
            Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
        ],
    )
    r = await a.run(Goal("拼接", session_id="wf"))
    print(r.status, r.answer)

    print("=== 4. pe ===")
    plan = Plan(id="p1", steps=[
        Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
        Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
    ])
    a = build_pe(
        model=FakeModel([answer("unused")]),
        planner=ScriptedPlanner(plan),
        tools=[concat],
    )
    r = await a.run(Goal("拼接", session_id="pe"))
    print(r.status, r.answer)

    print("=== 5. production ===")
    tracer = MemoryTracer()
    kb = InMemoryKnowledge([Recalled("订单 A1001 已签收", source="tenant=default")])
    a = build_production(
        model=FakeModel([tool_call("get_order", order_id="A1001"), answer("已签收")]),
        tools=[get_order],
        guard=AllowAllGuard(),
        budget=Budget(tokens=2000, calls=4),
        tracer=tracer,
        durability=MemoryDurability(),
        knowledge=kb,
        retrieval=AutoRetrieval(k=1),
    )
    r = await a.run(Goal("A1001 状态", session_id="prod"))
    print(r.status, r.answer, "events=", len(tracer.events))


if __name__ == "__main__":
    asyncio.run(main())
