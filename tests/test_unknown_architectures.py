"""「框架作者没想过的架构」验收（PROPOSAL §8、§11、§13）。

判据：让框架源码 diff = 0 的架构跑起来，且控制流完全定义在框架之外。
四种架构全部写在 ``examples/unknown_architectures.py``（纯用户侧），
本测试从那里导入并机械检查内核源码不认识它们。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PKG = ROOT / "src" / "harness"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import unknown_architectures as U  # noqa: E402  （用户侧代码）

from harness.contracts.decision import Decision, FnProgram, Halt, capabilities  # noqa: E402
from harness.contracts.types import Effect  # noqa: E402
from harness.fp.frontends import make_state  # noqa: E402
from harness.kernel.interpret import Limits, Runtime, interpret  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def runtime() -> Runtime:
    return Runtime(limits=Limits(max_transitions=64, max_calls=80))


KERNEL_FILES = (
    PKG / "contracts" / "decision.py",
    PKG / "kernel" / "interpret.py",
    PKG / "kernel" / "effects.py",
)
UNKNOWN_NAMES = ("Backtrack", "SelfModifying", "ExternalControl", "bare_transition")


class UnknownArchitectureTest(unittest.TestCase):
    def test_all_four_unknown_architectures_complete(self):
        cases = U.custom_cases()
        self.assertEqual(len(cases), 4)
        for name, program, state in cases:
            with self.subTest(name=name):
                out = run(runtime().interpret(program, state))
                self.assertEqual(out.status, "completed", f"{name}: {out.trace}")
                self.assertEqual(out.checkpoints, out.transitions)

    def test_backtrack_uses_restore_and_keeps_journal(self):
        """回溯撤销业务状态，但不撤销已消费的模型脚本进度（PROPOSAL §4.1）。"""
        name, program, state = U.custom_cases()[0]
        out = run(runtime().interpret(program, state))
        self.assertEqual(out.answer, "BETA")
        self.assertTrue(any("backtrack" in t for t in out.trace))
        self.assertEqual(state.journal.get("cursor"), 2)
        self.assertGreater(state.usage["calls"], 0)

    def test_self_modifying_rewrites_control_flow_at_runtime(self):
        _name, program, state = U.custom_cases()[1]
        out = run(runtime().interpret(program, state))
        self.assertIn("共 3 代", out.answer)
        self.assertIn("gen0:n1", out.trace[1])
        self.assertIn("gen1:n3", out.trace[2])   # 剩余节点被运行时重排
        self.assertIn("gen2:n2", out.trace[3])

    def test_external_system_owns_control(self):
        _name, program, state = U.custom_cases()[2]
        out = run(runtime().interpret(program, state))
        self.assertEqual(out.answer, "外部系统叫停（执行了 2 条指令）")
        self.assertIn("[wait]", out.trace[1])

    def test_bare_function_needs_no_class(self):
        _name, program, state = U.custom_cases()[3]
        self.assertIsInstance(program, FnProgram)
        self.assertEqual(capabilities(program),
                         {"describe": False, "to_spec": False, "static_check": False})
        out = run(runtime().interpret(program, state))
        self.assertEqual(out.answer, "裸函数")

    def test_kernel_source_does_not_know_these_architectures(self):
        """框架 diff = 0：内核三个文件里没有这些名字，也没有 import 前端库。"""
        for path in KERNEL_FILES:
            source = path.read_text(encoding="utf-8")
            for name in UNKNOWN_NAMES:
                self.assertNotIn(name, source, f"{path.name} 里出现了用户架构名 {name}")
            self.assertNotIn("frontends", source, f"{path.name} 不应依赖内置前端库")

    def test_examples_module_only_imports_public_api(self):
        source = (EXAMPLES / "unknown_architectures.py").read_text(encoding="utf-8")
        self.assertIn("harness.contracts.decision", source)
        self.assertIn("harness.kernel.interpret", source)
        self.assertNotIn("harness.kernel.legacy", source)

    def test_kernel_runs_without_any_frontends(self):
        """删掉整个 frontends.py，裸函数程序照样跑。"""
        prog = FnProgram(
            lambda s: Decision(
                effects=(Effect("compute", args={"op": "concat", "args": ["无", "前端"]},
                                key="k"),),
                program=FnProgram(lambda x: Halt(str(x.data["last_output"])), name="end"),
            ), name="no_frontends",
        )
        out = run(interpret(prog, make_state("x")))
        self.assertEqual(out.answer, "无前端")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
