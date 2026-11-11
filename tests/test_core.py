"""核心契约与循环的离线测试：无模型、无网络。"""

from __future__ import annotations

import asyncio
import unittest

from harness import (
    Budget,
    Decision,
    Goal,
    GuardDecision,
    MemorySink,
    RunStatus,
    Step,
)
from harness.assembly import HarnessConfig, build_harness
from harness.fp import Harness, react, workflow
from harness.parts.tools import tool
from support import FakeModel, answer, tool_call


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
        h = Harness.of(model=model, tools=[add])
        result = asyncio.run(h.run(react(max_steps=4), Goal("2+3")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "结果是 5")
        self.assertEqual(model.calls, 2)
        self.assertEqual(result.state.step_index, 1)

    def test_guard_deny(self):
        model = FakeModel([tool_call("add", a=1, b=1)])
        h = Harness.of(model=model, tools=[add], guard=DenyGuard())
        result = asyncio.run(h.run(react(max_steps=4), Goal("1+1")))
        self.assertEqual(result.status, RunStatus.REFUSED)
        self.assertIn("不允许", result.error)

    def test_budget_exhausted(self):
        model = FakeModel([answer("never")])
        h = Harness.of(model=model, budget=Budget(tokens=0, calls=1))
        result = asyncio.run(h.run(react(max_steps=4), Goal("hi")))
        # v3.1（SUPPLEMENT A4）：预算已映射进解释器 Limits，耗尽由护栏
        # 统一触发 degraded（reason=max_tokens），程序不再自查。
        self.assertEqual(result.status, RunStatus.DEGRADED)
        self.assertEqual(result.answer, "max_tokens")

    def test_approval_resume(self):
        model = FakeModel([tool_call("add", a=2, b=2), answer("4")])
        from harness.impl.stores import MemoryCheckpointStore

        h = Harness.of(model=model, tools=[add], guard=AskGuard(),
                       checkpoint_store=MemoryCheckpointStore())
        first = asyncio.run(h.run(react(max_steps=4), Goal("2+2", session_id="s1")))
        self.assertEqual(first.status, RunStatus.NEEDS_APPROVAL)
        self.assertIsNotNone(first.pending)

        second = asyncio.run(h.resume(react(max_steps=4), "s1", Decision.approve("alice")))
        self.assertEqual(second.status, RunStatus.COMPLETED)
        self.assertEqual(second.answer, "4")

    def test_workflow(self):
        model = FakeModel([answer("unused")])
        h = Harness.of(model=model, tools=[concat])
        program = workflow(
            Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
            Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
        )
        result = asyncio.run(h.run(program, Goal("拼接")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "cd")

    def test_build_harness_entry(self):
        """build_harness → Harness：配置入口直连同一运行时。"""
        from harness.impl.stores import MemoryCheckpointStore

        h = build_harness(HarnessConfig(
            tools=(concat,),
            checkpoint_store=MemoryCheckpointStore(),
        ))
        h.model = FakeModel([answer("ok")])
        result = asyncio.run(h.run(react(max_steps=2), Goal("hi", session_id="cfg")))
        self.assertEqual(result.status, RunStatus.COMPLETED)

    def test_tracer(self):
        """BL-4：事件单轨——观测统一走 EventSink（RunEvent）。"""
        sink = MemorySink()
        model = FakeModel([answer("ok")])
        h = Harness.of(model=model)
        asyncio.run(h.run(react(max_steps=4), Goal("hi"), sinks=(sink,)))
        names = [event.name for event in sink.events]
        self.assertIn("run.start", names)
        self.assertIn("run.end", names)


if __name__ == "__main__":
    unittest.main()
