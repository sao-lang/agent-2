"""四种拓扑的离线测试。"""

from __future__ import annotations

import asyncio
import unittest

from harness import (
    AgentConfig,
    Blackboard,
    Goal,
    Handoff,
    Pipeline,
    Route,
    RuleRouter,
    RunStatus,
    Supervisor,
    build,
)
from harness.testing import FakeModel, answer


def make(text: str):
    return build(AgentConfig(model=FakeModel([answer(text)]), name=text))


class TestTopology(unittest.TestCase):
    def test_pipeline(self):
        team = Pipeline([make("a"), make("b")])
        result = asyncio.run(team.run(Goal("start", session_id="p")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "b")

    def test_handoff(self):
        team = Handoff(
            agents={"refund": make("退款处理"), "general": make("普通回答")},
            router=RuleRouter(routes=[
                Route("refund", accepts=["退款"]),
                Route("general", fallback=True),
            ]),
        )
        result = asyncio.run(team.run(Goal("我要退款", session_id="h")))
        self.assertEqual(result.answer, "退款处理")

    def test_supervisor(self):
        team = Supervisor(
            workers={"research": make("资料"), "write": make("报告")},
            plan=lambda goal: [("research", "查资料"), ("write", "写报告")],
            synth=lambda results: " | ".join(item.answer for item in results.values()),
        )
        result = asyncio.run(team.run(Goal("写报告", session_id="s")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "资料 | 报告")

    def test_blackboard(self):
        team = Blackboard(
            agents=[make("发现一"), make("发现二")],
            reducer=lambda board: " / ".join(board.values()),
        )
        result = asyncio.run(team.run(Goal("调研", session_id="b")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertIn("发现一", result.answer)
        self.assertIn("发现二", result.answer)


if __name__ == "__main__":
    unittest.main()
