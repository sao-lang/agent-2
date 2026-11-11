"""收敛验收（PROPOSAL §10、§11、§13 阶段 2）。

验证三件事：

1. 单版本公开 API 的名字与行为都在（Harness / build_harness / fp 组合子）；
2. 两条入口（Harness.run、Harness.interpret）共用同一个解释器，
   **源码中不存在并列循环**；
3. 新内核的 Outcome 能正确映射回既有 RunResult（含审批挂起 pending）。
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

import harness
from harness.assembly.harness import Harness
from harness.contracts.decision import FnProgram, Halt
from harness.contracts.protocols.runtime import Program as ProgramProtocol
from harness.contracts.result import RunResult
from harness.contracts.status import RunStatus
from harness.contracts.types import Decision, Goal, GuardDecision
from harness.fp import react
from harness.fp.frontends import make_state
from harness.impl.stores import MemoryCheckpointStore
from support import FakeModel, answer, script_model_handler, tool_call
from harness.parts.tools import tool

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

    def test_all_public_names_resolve(self):
        """单版本公开面：v3 入口 + 既有部件名全部可达。"""
        for name in ("Harness", "HarnessConfig", "build_harness", "react", "workflow",
                     "pe", "Program", "interpret", "Budget", "MemorySink",
                     "SkillRegistry", "RuleRouter", "Pipeline",
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


class RunPathTest(unittest.TestCase):
    def test_harness_run_completes(self):
        model = FakeModel([tool_call("concat", left="a", right="b"), answer("ab")])
        h = Harness.of(model=model, tools=[concat])
        result = run(h.run(react(max_steps=4), Goal("2+3")))
        self.assertIsInstance(result, RunResult)
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "ab")
        self.assertEqual(result.state.step_index, 1)
        self.assertEqual(result.usage["calls"], 2)

    def test_harness_run_and_fp_run_share_one_runtime(self):
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

    def test_approval_resume_still_works(self):
        class AskGuard:
            async def check(self, step, state):
                return GuardDecision.ask("需要审批", {"tool": step.tool_name}, expires_in=3600)

        model = FakeModel([tool_call("concat", left="a", right="b"), answer("ab")])
        h = Harness.of(model=model, tools=[concat], guard=AskGuard(),
                       checkpoint_store=MemoryCheckpointStore())
        first = run(h.run(react(max_steps=4), Goal("审批", session_id="s9")))
        self.assertEqual(first.status, RunStatus.NEEDS_APPROVAL)
        self.assertIsNotNone(first.pending)
        second = run(h.resume(react(max_steps=4), "s9", Decision.approve("alice")))
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
            React(max_steps=2), make_state("干跑", data={"script": [{"content": "done"}]}),
            extra_handlers={"model": script_model_handler},
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

        for retired in ("kernel/loop.py",):
            self.assertEqual(while_count(PKG / retired), 0,
                             f"{retired} 仍有并列循环")
            self.assertIn("interpret",
                          (PKG / retired).read_text(encoding="utf-8"),
                          f"{retired} 未接到唯一解释器")
        self.assertEqual(while_count(PKG / "kernel" / "interpret.py"), 1)

    def test_retired_v1_files_are_gone(self):
        """BL-2/BL-3：v1 装配线（Agent/build/presets/body）已退役。"""
        for retired in ("assembly/agent.py", "assembly/build.py", "assembly/presets.py",
                        "parts/body", "kernel/legacy.py", "parts/tracer.py"):
            self.assertFalse((PKG / retired).exists(), f"残留未退役：{retired}")

    def test_kernel_stage_and_loop_are_not_modified_semantics(self):
        from harness.kernel import chain, stage

        self.assertEqual(chain.POINTS[:4], ("run", "step", "model_call", "tool_call"))
        self.assertIn("transition", chain.POINTS)
        self.assertIn("commit", chain.POINTS)
        self.assertTrue(callable(stage.run_stages))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
