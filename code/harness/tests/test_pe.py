"""Plan-and-Execute 的离线测试。"""

from __future__ import annotations

import asyncio
import unittest

from harness import (
    AgentConfig,
    ConfigError,
    Goal,
    Plan,
    RunStatus,
    ScriptedPlanner,
    Step,
    build,
    tool,
)
from harness.testing import FakeModel, answer


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


class TestPlanExecute(unittest.TestCase):
    def test_plan_runs_in_order(self):
        plan = Plan(id="p1", steps=[
            Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
            Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
        ])
        agent = build(AgentConfig(
            model=FakeModel([answer("unused")]),
            tools=[concat],
            mode="pe",
            planner=ScriptedPlanner(plan),
        ))
        result = asyncio.run(agent.run(Goal("拼接")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "cd")
        self.assertEqual(result.state.data["pe"]["plan"]["id"], "p1")
        self.assertEqual(result.state.data["pe"]["index"], 2)

    def test_pe_requires_planner(self):
        with self.assertRaises(ConfigError):
            build(AgentConfig(model=FakeModel([answer("x")]), mode="pe"))

    def test_react_rejects_planner(self):
        plan = Plan(id="p1", steps=[])
        with self.assertRaises(ConfigError):
            build(AgentConfig(
                model=FakeModel([answer("x")]),
                mode="react",
                planner=ScriptedPlanner(plan),
            ))


if __name__ == "__main__":
    unittest.main()
