"""Plan-and-Execute 的离线测试（v3 入口）。"""

from __future__ import annotations

import asyncio
import unittest

from harness import Goal, Plan, RunStatus, Step
from harness.fp import Harness, pe as pe_program, react as react_program
from harness.parts.policy import ScriptedPlanner
from harness.parts.tools import tool
from support import FakeModel, answer


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
        h = Harness.of(model=FakeModel([answer("unused")]), tools=[concat])
        program = pe_program(ScriptedPlanner(plan))
        result = asyncio.run(h.run(program, Goal("拼接")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "cd")
        self.assertEqual(result.state.data["pe"]["plan"]["id"], "p1")
        self.assertEqual(result.state.data["pe"]["index"], 2)

    def test_pe_requires_planner(self):
        """pe 不给 planner 要显式报错（v3 中 planner 是必填位置参数）。"""
        with self.assertRaises(TypeError):
            pe_program()

    def test_react_rejects_planner(self):
        """react 不接受 planner——非法组合在 v3 中不可表达，显式报错。"""
        plan = Plan(id="p1", steps=[])
        with self.assertRaises(TypeError):
            react_program(planner=ScriptedPlanner(plan))


if __name__ == "__main__":
    unittest.main()
