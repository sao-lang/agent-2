"""同一个退款问答的两种写法：耦合版与基座版。

不联网；模型是固定剧本。这个脚本只演示“改动点在哪里”，不比较答案质量。

运行：
    $env:PYTHONPATH="code/harness/src"
    python code/harness/examples/coupling.py
"""

from __future__ import annotations

import asyncio

from harness import AgentConfig, Budget, Goal, build, tool
from harness.testing import FakeModel, answer, tool_call


async def get_order_data(order_id: str) -> dict:
    return {"order_id": order_id, "status": "已签收", "signed_days_ago": 3, "opened": False}


@tool
async def get_order(order_id: str) -> dict:
    """查询订单。"""
    return await get_order_data(order_id)


@tool
async def check_policy(order_id: str) -> dict:
    """查询退货政策。"""
    return {"window_days": 7, "require_unopened": True}


class BeforeAgent:
    """耦合版：模型、工具、Guard、预算全在 run() 里。"""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, text: str) -> str:
        self.calls += 1
        order_id = text.split()[-1]
        # 1. 这里直接假设模型会调 get_order
        order = await get_order_data(order_id)
        # 2. 这里直接假设政策窗口是 7 天
        if order["signed_days_ago"] > 7 or order["opened"]:
            return "不能退"
        # 3. 这里直接拼答复
        return f"{order_id} 已签收 {order['signed_days_ago']} 天、未拆封，可以退。"


async def after_agent() -> str:
    model = FakeModel([
        tool_call("get_order", order_id="A1001"),
        tool_call("check_policy", order_id="A1001"),
        answer("A1001 已签收 3 天、未拆封，可以退。"),
    ])
    agent = build(AgentConfig(
        model=model,
        tools=[get_order, check_policy],
        mode="react",
        budget=Budget(tokens=20_000, calls=8),
    ))
    result = await agent.run(Goal("订单 A1001 还能退吗", session_id="demo"))
    return result.answer


async def main() -> None:
    before = BeforeAgent()
    print("=== 1. 耦合版 ===")
    print("  改动模型：改 BeforeAgent.run 里的模型调用")
    print("  加 Guard：在 run 里插 if")
    print("  换政策：改 run 里的 7 天")
    print("  answer:", await before.run("订单 A1001"))

    print()
    print("=== 2. 基座版 ===")
    print("  改动模型：换 AgentConfig.model")
    print("  加 Guard：换 AgentConfig.guard")
    print("  换政策：check_policy 一个工具")
    print("  answer:", await after_agent())


if __name__ == "__main__":
    asyncio.run(main())
