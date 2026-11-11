"""P5 门面演示：三个类型 + 组合 + 端到端运行。

运行：
    $env:PYTHONPATH="src"
    python examples/fp_facade.py
"""

from __future__ import annotations

import asyncio

from harness import Goal, Step
from harness.fp import Harness, describe, react, workflow
from harness.impl.stores import MemoryCheckpointStore
from harness.parts.middleware import budget_layer, taskboard_layer
from harness.parts.tools import tool
from harness.testing import FakeModel, answer, tool_call


@tool
async def get_order(order_id: str) -> dict:
    """查询订单。

    Args:
        order_id: 订单号
    """
    return {"order_id": order_id, "status": "已签收"}


def checkpoint(store) -> object:
    from harness.parts.middleware.base import layer

    def build(nxt):
        async def handler(req):
            await store.put(_ns(), req.state.session.session_id, req.state,
                            expect_rev=req.state.rev)
            return await nxt(req)

        return handler

    return layer("checkpoint", ["step"], build)


def _ns():
    from harness.contracts.types import Namespace

    return Namespace()


async def main() -> None:
    store = MemoryCheckpointStore()

    # ① 程序：一个 body + 若干层，纯值
    program = (
        react(max_steps=6)
        >> budget_layer(budget=__import__("harness", fromlist=["Budget"]).Budget(tokens=5000))
        >> taskboard_layer()
        >> checkpoint(store)
    )
    print("① describe(program)")
    print("   ", describe(program))

    # ② 运行器：能力注入
    harness = Harness.of(
        model=FakeModel([tool_call("get_order", order_id="A1001"), answer("A1001 已签收")]),
        tools=[get_order],
        system="你是客服",
    )
    result = await harness.run(program, Goal("查 A1001", session_id="demo"))
    print("② 运行结果")
    print(f"    状态={result.status}  答案={result.answer}  用量={result.usage}")
    print(f"    检查点={await store.history(_ns(), 'demo')}")

    # ③ 同一 Harness，换 body：固定流程不调模型
    fixed = workflow(
        Step(id="a", tool_name="get_order", args={"order_id": "B1"}),
    )
    harness2 = Harness.of(model=FakeModel([answer("unused")]), tools=[get_order])
    out = await harness2.run(fixed, Goal("固定流程", session_id="wf"))
    print("③ workflow（不调模型）")
    print(f"    状态={out.status}  答案={out.answer}")

    # ④ 干跑：四段照走，终端不执行
    fresh = Harness.of(model=FakeModel([tool_call("get_order", order_id="C3"), answer("done")]),
                       tools=[get_order])
    dry = await fresh.dry_run(react(max_steps=6) >> taskboard_layer(),
                              Goal("先看会做什么", session_id="dry"))
    print("④ dry_run 收集到的效果")
    print("   ", [(e.kind, e.step.tool_name) for e in dry])


if __name__ == "__main__":
    asyncio.run(main())
