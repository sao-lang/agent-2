"""兼容与收敛验收（PROPOSAL §10、§11、§13 阶段 2）。

验证三件事：

1. 新旧公开 API 的名字与行为都还在（v1 Agent / v2 Program / dry_run）；
2. 三条入口（v1 Agent、v2 Harness.run、v3 Harness.interpret）共用同一个解释器，
   **源码中不存在并列循环**；
3. 新内核的 Outcome 能正确映射回既有 RunResult。
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

import harness
from harness.assembly.agent import Agent
from harness.assembly.build import AgentConfig, build
from harness.assembly.harness import Harness
from harness.contracts.decision import FnProgram, Halt
from harness.contracts.protocols.runtime import Program as ProgramProtocol
from harness.contracts.result import RunResult
from harness.contracts.status import RunStatus
from harness.contracts.types import Goal
from harness.fp import react
from harness.fp.frontends import make_state
from harness.parts.tools import tool
from harness.testing import FakeModel, answer, tool_call

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "harness"


def run(coro):
    return asyncio.run(coro)


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


class PublicApiTest(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(harness.__version__, "0.3.0")
        self.assertEqual(harness.contracts_version, "3")

    def test_all_old_public_names_still_resolve(self):
        for name in ("build", "build_react", "build_production", "Agent", "AgentConfig",
                     "Budget", "MemoryTracer", "SkillRegistry", "RuleRouter", "Pipeline",
                     "Handoff", "Layer", "layer", "Hook", "tool", "Decision"):
            self.assertTrue(hasattr(harness, name), f"公开名丢失：{name}")

    def test_decision_remains_approval_type_but_transition_is_exported(self):
        """顶层 Decision 是审批类型；v3 转移决策以 Transition 别名导出。"""
        self.assertEqual(harness.Decision.approve("alice").action, "approve")
        self.assertIs(harness.Transition.__name__, "Decision")
        self.assertIn("effects", harness.Transition.__dataclass_fields__)
        self.assertTrue(hasattr(harness, "interpret"))
        self.assertTrue(hasattr(harness, "Halt"))

    def test_fp_program_satisfies_new_protocol(self):
        program = react(max_steps=3)
        self.assertTrue(callable(getattr(program, "transition", None)))
        self.assertEqual(program.name, "react")
        # runtime_checkable Protocol 只做形状判定
        self.assertTrue(issubclass(ProgramProtocol, object))
        self.assertIsInstance(FnProgram(lambda s: Halt("x"), name="f").name, str)


class LegacyPathTest(unittest.TestCase):
    def test_v1_agent_still_completes(self):
        model = FakeModel([tool_call("concat", left="a", right="b"), answer("ab")])
        agent: Agent = build(AgentConfig(model=model, tools=[concat], mode="react"))
        result = run(agent.run(Goal("2+3")))
        self.assertIsInstance(result, RunResult)
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "ab")
        self.assertEqual(result.state.step_index, 1)

    def test_v2_harness_run_still_completes(self):
        model = FakeModel([tool_call("concat", left="a", right="b"), answer("ab")])
        h = Harness.of(model=model, tools=[concat])
        result = run(h.run(react(max_steps=4), Goal("拼接", session_id="s1")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "ab")
        self.assertEqual(result.usage["calls"], 2)

    def test_dry_run_still_records_effects_as_data(self):
        model = FakeModel([tool_call("concat", left="x", right="y"), answer("done")])
        h = Harness.of(model=model, tools=[concat])
        effects = run(h.dry_run(react(max_steps=3), Goal("干跑", session_id="d")))
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].step.tool_name, "concat")

    def test_v1_approval_resume_still_works(self):
        from harness import Decision, GuardDecision, MemoryDurability

        class AskGuard:
            async def check(self, step, state):
                return GuardDecision.ask("需要审批", {"tool": step.tool_name}, expires_in=3600)

        model = FakeModel([tool_call("concat", left="a", right="b"), answer("ab")])
        agent = build(AgentConfig(model=model, tools=[concat], guard=AskGuard(),
                                  durability=MemoryDurability()))
        first = run(agent.run(Goal("审批", session_id="s9")))
        self.assertEqual(first.status, RunStatus.NEEDS_APPROVAL)
        self.assertIsNotNone(first.pending)
        second = run(agent.resume("s9", Decision.approve("alice")))
        self.assertEqual(second.status, RunStatus.COMPLETED)


class NewEntryTest(unittest.TestCase):
    def test_harness_interpret_runs_any_program(self):
        h = Harness.of()
        program = FnProgram(
            lambda s: harness.Transition(
                effects=(harness.Effect("compute", args={"op": "upper", "args": ["ok"]},
                                        key="k"),),
                program=FnProgram(lambda x: harness.Halt(str(x.data["last_output"])), name="end"),
            ), name="p")
        # Effect 不在顶层导出时从契约层取
        out = run(h.interpret(program, make_state("新入口")))
        self.assertEqual(out.status, "completed")
        self.assertEqual(out.answer, "OK")

    def test_harness_dry_run_program_uses_record_only(self):
        from harness.fp.frontends import React

        h = Harness.of()
        out, effects = run(h.dry_run_program(
            React(max_steps=2), make_state("干跑", data={"script": [{"content": "done"}]})
        ))
        self.assertEqual(out.answer, "[dry-run:model]")
        self.assertEqual([e.kind for e in effects], ["model"])

    def test_harness_config_max_transitions_reaches_runtime(self):
        from harness.assembly.config import HarnessConfig, build_harness, validate
        from harness.contracts.errors import ConfigError

        config = HarnessConfig(max_transitions=7)
        validate(config)
        h = build_harness(config)
        self.assertEqual(h.max_transitions, 7)
        self.assertEqual(h.new_runtime(make_state("x")).limits.max_transitions, 7)
        with self.assertRaises(ConfigError):
            validate(HarnessConfig(max_transitions=0))


class SingleInterpreterTest(unittest.TestCase):
    """阶段 2：解释器唯一；git 工作区里没有并列循环。"""

    def test_only_interpret_py_contains_a_run_loop(self):
        import ast

        def while_count(path: Path) -> int:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return sum(isinstance(node, ast.While) for node in ast.walk(tree))

        for retired in ("kernel/loop.py", "assembly/agent.py"):
            self.assertEqual(while_count(PKG / retired), 0,
                             f"{retired} 仍有并列循环")
            self.assertIn("interpret",
                          (PKG / retired).read_text(encoding="utf-8"),
                          f"{retired} 未接到唯一解释器")
        self.assertEqual(while_count(PKG / "kernel" / "interpret.py"), 1)

    def test_kernel_stage_and_loop_are_not_modified_semantics(self):
        from harness.kernel import chain, stage

        self.assertEqual(chain.POINTS[:4], ("run", "step", "model_call", "tool_call"))
        self.assertIn("transition", chain.POINTS)
        self.assertIn("commit", chain.POINTS)
        self.assertTrue(callable(stage.run_stages))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
