"""DoD 冒烟：五个预设 + 四种拓扑各跑一次（SPEC §21.2）。"""

from __future__ import annotations

import asyncio
import unittest

from harness.assembly import HarnessConfig, build_harness
from harness.assembly.fpresets import minimal, pe, production, react as react_cfg, workflow as wf_cfg
from harness.contracts.result import RunResult
from harness.contracts.status import RunStatus
from harness.contracts.types import Goal, Plan, Step
from harness.fp import pe as pe_program
from harness.fp import react as react_program
from harness.fp import workflow as wf_program
from harness.parts.body import ScriptedPlanner
from harness.parts.topology import Blackboard, Handoff, Pipeline, Supervisor
from harness.parts.tools import tool
from harness.testing import FakeModel, answer, tool_call


def run(coro):
    return asyncio.run(coro)


@tool
def echo(text: str) -> str:
    """回显。"""
    return text


class PresetSmokeTest(unittest.TestCase):
    """五个预设各跑一次。"""

    def test_minimal(self):
        h = build_harness(minimal(model="fake", tools=(echo,)))
        h.model = FakeModel([answer("ok")])
        self.assertEqual(run(h.run(react_program(max_steps=2), Goal("x", session_id="m"))).status,
                         RunStatus.COMPLETED)

    def test_react(self):
        h = build_harness(react_cfg(model="fake", tools=(echo,)))
        h.model = FakeModel([tool_call("echo", text="hi"), answer("done")])
        result = run(h.run(react_program(max_steps=3), Goal("x", session_id="r")))
        self.assertEqual(result.answer, "done")

    def test_workflow(self):
        h = build_harness(wf_cfg(model="fake", tools=(echo,)))
        program = wf_program(Step(id="a", tool_name="echo", args={"text": "hi"}))
        self.assertEqual(run(h.run(program, Goal("x", session_id="w"))).status,
                         RunStatus.COMPLETED)

    def test_pe(self):
        h = build_harness(pe(model="fake", tools=(echo,)))
        plan = Plan(id="p", steps=[Step(id="a", tool_name="echo", args={"text": "hi"})])
        program = pe_program(ScriptedPlanner(plan), max_steps=3)
        self.assertEqual(run(h.run(program, Goal("x", session_id="p"))).status,
                         RunStatus.COMPLETED)

    def test_production(self):
        h = build_harness(production(model="fake", tools=(echo,)))
        h.model = FakeModel([answer("ok")])
        result = run(h.run(react_program(max_steps=2), Goal("正常请求", session_id="prod")))
        self.assertEqual(result.status, RunStatus.COMPLETED)   # 干净输入不被护栏拦
        self.assertEqual(len(h.guardrails), 3)


class TopologySmokeTest(unittest.TestCase):
    """四种拓扑各跑一次。"""

    class _Agent:
        def __init__(self, name: str, out: str) -> None:
            self.name, self.out = name, out

        async def run(self, goal, *, scope=None):
            return RunResult(status=RunStatus.COMPLETED, answer=self.out)

    def test_pipeline(self):
        out = run(Pipeline([self._Agent("a", "一"), self._Agent("b", "二")]).run(Goal("x")))
        self.assertEqual(out.answer, "二")

    def test_handoff(self):
        from harness.parts.dispatch import AlwaysRoute

        out = run(Handoff({"a": self._Agent("a", "交给 a")}, AlwaysRoute("a")).run(Goal("x")))
        self.assertEqual(out.answer, "交给 a")

    def test_supervisor(self):
        sup = Supervisor(
            workers={"w": self._Agent("w", "子结论")},
            plan=lambda goal: [("w", "子任务")],
            synth=lambda results: "汇总：" + "；".join(r.answer for r in results.values()),
        )
        out = run(sup.run(Goal("x")))
        self.assertEqual(out.answer, "汇总：子结论")

    def test_blackboard(self):
        board = Blackboard(
            agents=[self._Agent("a", "甲"), self._Agent("b", "乙")],
            reducer=lambda b: "+".join(sorted(b.values())),
        )
        out = run(board.run(Goal("x")))
        self.assertEqual(out.answer, "乙+甲")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
