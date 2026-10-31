"""四种拓扑：同一批 Agent，只换组合方式。

运行：
    $env:PYTHONPATH="code/harness/src"
    python code/harness/examples/topology.py
"""

from __future__ import annotations

import asyncio

from harness import (
    AgentConfig,
    Blackboard,
    Goal,
    Handoff,
    Pipeline,
    Route,
    RuleRouter,
    Supervisor,
    build,
)
from harness.testing import FakeModel, answer


def make(text: str):
    return build(AgentConfig(model=FakeModel([answer(text)]), name=text))


async def main() -> None:
    goal = Goal("同一个任务", session_id="topo")

    pipe = Pipeline([make("解析"), make("分析"), make("写报告")])
    print("pipeline:", (await pipe.run(goal)).answer)

    handoff = Handoff(
        agents={"refund": make("退款处理"), "general": make("普通回答")},
        router=RuleRouter(routes=[
            Route("refund", accepts=["退款"]),
            Route("general", fallback=True),
        ]),
    )
    print("handoff:", (await handoff.run(Goal("我要退款", session_id="h"))).answer)

    supervisor = Supervisor(
        workers={"research": make("资料"), "write": make("报告")},
        plan=lambda g: [("research", "查资料"), ("write", "写报告")],
        synth=lambda results: " | ".join(item.answer for item in results.values()),
    )
    print("supervisor:", (await supervisor.run(goal)).answer)

    board = Blackboard(
        agents=[make("发现一"), make("发现二")],
        reducer=lambda items: " / ".join(items.values()),
    )
    print("blackboard:", (await board.run(goal)).answer)


if __name__ == "__main__":
    asyncio.run(main())
