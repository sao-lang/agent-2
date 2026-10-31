"""最小示例：ReAct + 工具 + 预算 + 轨迹。

运行：
    $env:PYTHONPATH="code/harness/src"
    python code/harness/examples/refund_agent.py
"""

from __future__ import annotations

import asyncio

from harness import AgentConfig, Budget, Goal, MemoryTracer, build, tool
from harness.testing import FakeModel, answer, tool_call


@tool
async def get_order(order_id: str) -> dict:
    """查询订单状态与签收时间。"""
    return {"order_id": order_id, "status": "已签收", "signed_days_ago": 3, "opened": False}


@tool
async def check_policy(order_id: str) -> dict:
    """查询退货政策。"""
    return {"window_days": 7, "require_unopened": True}


async def main() -> None:
    model = FakeModel([
        tool_call("get_order", order_id="A1001"),
        tool_call("check_policy", order_id="A1001"),
        answer("订单 A1001 已签收 3 天、未拆封，仍在 7 天窗口内，可以退。"),
    ])
    tracer = MemoryTracer()
    agent = build(AgentConfig(
        model=model,
        tools=[get_order, check_policy],
        mode="react",
        budget=Budget(tokens=20_000, calls=8),
        tracer=tracer,
    ))

    result = await agent.run(Goal("订单 A1001 还能退吗？", user_id="u1", session_id="s1"))
    print("status:", result.status)
    print("answer:", result.answer)
    print("steps:", result.state.step_index)
    print("usage:", result.usage)
    print("trace:", [event.name for event in tracer.events])


if __name__ == "__main__":
    asyncio.run(main())
