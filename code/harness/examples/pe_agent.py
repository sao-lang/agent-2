"""Plan-and-Execute 示例：固定计划、逐步执行。

运行：
    $env:PYTHONPATH="code/harness/src"
    python code/harness/examples/pe_agent.py
"""

from __future__ import annotations

import asyncio

from harness import (
    AgentConfig,
    Goal,
    Plan,
    ScriptedPlanner,
    Step,
    build,
    tool,
)
from harness.testing import FakeModel, answer


@tool
async def fetch_order(order_id: str) -> dict:
    """查询订单。"""
    return {"order_id": order_id, "status": "已签收", "signed_days_ago": 3}


@tool
async def decide_refund(order_id: str, signed_days_ago: int) -> str:
    """按政策判断是否可退。"""
    return "可以退" if signed_days_ago <= 7 else "不能退"


async def main() -> None:
    plan = Plan(id="refund-plan", steps=[
        Step(id="s1", tool_name="fetch_order", args={"order_id": "A1001"}),
        Step(id="s2", tool_name="decide_refund",
             args={"order_id": "A1001", "signed_days_ago": 3}),
    ])
    agent = build(AgentConfig(
        model=FakeModel([answer("unused")]),
        tools=[fetch_order, decide_refund],
        mode="pe",
        planner=ScriptedPlanner(plan),
    ))
    result = await agent.run(Goal("判断 A1001 能不能退", session_id="pe-demo"))
    print("status:", result.status)
    print("answer:", result.answer)
    print("plan_id:", result.state.data["pe"]["plan"]["id"])
    print("index:", result.state.data["pe"]["index"])


if __name__ == "__main__":
    asyncio.run(main())
