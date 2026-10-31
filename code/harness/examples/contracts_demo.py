"""契约演示：类型形状、非法配置、终止态。

不联网；模型是固定剧本。

运行：
    $env:PYTHONPATH="code/harness/src"
    python code/harness/examples/contracts_demo.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from harness import AgentConfig, Goal, RunStatus, Step, build
from harness.errors import ConfigError
from harness.testing import FakeModel, answer


def show_step() -> None:
    step = Step(
        id="s1",
        instruction="查订单",
        tool_name="get_order",
        args={"order_id": "A1001"},
        idem_key="order:A1001",
    )
    print("step =", json.dumps(asdict(step), ensure_ascii=False))


def show_invalid_config() -> None:
    try:
        build(AgentConfig(model=FakeModel([answer("x")]), mode="react", planner=object()))
    except ConfigError as exc:
        print("build 拒绝:", exc)


async def show_result() -> None:
    agent = build(AgentConfig(model=FakeModel([answer("可以退")]), mode="react"))
    result = await agent.run(Goal("A1001 能退吗", session_id="demo"))
    print("status =", result.status)
    print("answer =", result.answer)
    print("usage  =", result.usage)
    print("trace  =", bool(result.trace_id))


def main() -> None:
    print("=== 1. 一个 Step 的形状 ===")
    show_step()
    print()
    print("=== 2. 非法组合在装配时被拒绝 ===")
    show_invalid_config()
    print()
    print("=== 3. 终止态不是异常 ===")
    asyncio.run(show_result())
    print()
    print("=== 4. 六种终止态 ===")
    print([status.value for status in RunStatus])


if __name__ == "__main__":
    main()
