"""核心契约与循环的离线测试：无模型、无网络。"""

from __future__ import annotations

import asyncio
import unittest

from harness import (
    AgentConfig,
    Budget,
    Decision,
    Goal,
    GuardDecision,
    MemoryDurability,
    MemoryTracer,
    RunStatus,
    Step,
    build,
    tool,
)
from harness.testing import FakeModel, answer, tool_call


@tool
async def add(a: int, b: int) -> int:
    """两数相加。"""
    return a + b


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


class AskGuard:
    async def check(self, step, state):
        return GuardDecision.ask("需要审批", {"tool": step.tool_name}, expires_in=3600)


class DenyGuard:
    async def check(self, step, state):
        return GuardDecision.deny("不允许")


class TestCore(unittest.TestCase):
    def test_react_tool_call(self):
        model = FakeModel([tool_call("add", a=2, b=3), answer("结果是 5")])
        agent = build(AgentConfig(model=model, tools=[add], mode="react"))
        result = asyncio.run(agent.run(Goal("2+3")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "结果是 5")
        self.assertEqual(model.calls, 2)
        self.assertEqual(result.state.step_index, 1)

    def test_guard_deny(self):
        model = FakeModel([tool_call("add", a=1, b=1)])
        agent = build(AgentConfig(model=model, tools=[add], guard=DenyGuard()))
        result = asyncio.run(agent.run(Goal("1+1")))
        self.assertEqual(result.status, RunStatus.REFUSED)
        self.assertIn("不允许", result.error)

    def test_budget_exhausted(self):
        model = FakeModel([answer("never")])
        agent = build(AgentConfig(model=model, budget=Budget(tokens=0, calls=1)))
        result = asyncio.run(agent.run(Goal("hi")))
        self.assertEqual(result.status, RunStatus.DEGRADED)
        self.assertIn("budget", result.error)

    def test_approval_resume(self):
        model = FakeModel([tool_call("add", a=2, b=2), answer("4")])
        agent = build(AgentConfig(
            model=model,
            tools=[add],
            guard=AskGuard(),
            durability=MemoryDurability(),
        ))
        first = asyncio.run(agent.run(Goal("2+2", session_id="s1")))
        self.assertEqual(first.status, RunStatus.NEEDS_APPROVAL)
        self.assertIsNotNone(first.pending)

        second = asyncio.run(agent.resume("s1", Decision.approve("alice")))
        self.assertEqual(second.status, RunStatus.COMPLETED)
        self.assertEqual(second.answer, "4")

    def test_workflow(self):
        model = FakeModel([answer("unused")])
        agent = build(AgentConfig(
            model=model,
            tools=[concat],
            mode="workflow",
            workflow=[
                Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
                Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
            ],
        ))
        result = asyncio.run(agent.run(Goal("拼接")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "cd")

    def test_tracer(self):
        tracer = MemoryTracer()
        model = FakeModel([answer("ok")])
        agent = build(AgentConfig(model=model, tracer=tracer))
        asyncio.run(agent.run(Goal("hi")))
        names = [event.name for event in tracer.events]
        self.assertIn("run.start", names)
        self.assertIn("run.end", names)


if __name__ == "__main__":
    unittest.main()
