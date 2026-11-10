"""契约层测试（P2 验收）：类型冻结、七态、协议可判定、导出完整、序列化往返。"""

from __future__ import annotations

import dataclasses
import unittest

import harness.contracts as C


FROZEN_TYPES = [
    "Namespace", "SessionRef", "SessionMeta", "Goal", "Brief", "TaskSpec",
    "ToolCall", "Done", "ModelReply", "ModelDelta", "ResponseFormat", "Message",
    "Verdict", "GuardDecision", "Content", "GuardrailVerdict", "Decision", "Failure",
    "ActionResult", "ToolResult", "ExecResult", "Pack", "Recalled",
    "Section", "Frame", "Card", "Limits", "Mount", "ApprovalRequest",
    "Checkpoint", "Recorded", "Page", "ToolSpec", "ToolContext",
    "Document", "Job", "Match", "Stat", "ArtifactRef", "ArtifactMeta",
    "Effect", "LayerSpec", "ProgramSpec", "Route",
    "RunRequest", "StepRequest", "ModelRequest", "ToolRequest",
    "RunResponse", "StepResponse", "ModelResponse", "ToolResponse",
    "TraceEvent", "RunEvent", "HookEvent",
]

MUTABLE_TYPES = ["State", "Step", "Plan", "Board", "Budget", "RunContext", "StreamState"]


class StatusTest(unittest.TestCase):
    def test_exactly_seven_states(self):
        self.assertEqual(len(C.RunStatus), 7)

    def test_running_is_not_terminal(self):
        self.assertNotIn(C.RunStatus.RUNNING, C.TERMINAL_STATUSES)
        self.assertEqual(len(C.TERMINAL_STATUSES), 6)

    def test_enums_present(self):
        self.assertEqual([p.value for p in C.Point], ["run", "step", "model_call", "tool_call"])
        self.assertEqual(len(C.Gate5), 5)
        self.assertEqual(len(C.FrameKind), 4)
        self.assertEqual(len(C.SideEffect), 5)


class FreezeTest(unittest.TestCase):
    def test_marked_frozen(self):
        for name in FROZEN_TYPES:
            cls = getattr(C, name)
            self.assertTrue(cls.__dataclass_params__.frozen, f"{name} 必须 frozen")

    def test_marked_mutable(self):
        for name in MUTABLE_TYPES:
            cls = getattr(C, name)
            self.assertFalse(cls.__dataclass_params__.frozen, f"{name} 允许可变")

    def test_frozen_blocks_mutation(self):
        section = C.Section(name="goal")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            section.text = "x"  # type: ignore[misc]


class ProtocolTest(unittest.TestCase):
    """协议必须能在运行期判定，否则"可替换"无法机械检查。"""

    def test_builtin_impls_satisfy_protocols(self):
        from harness.parts.guard import AllowAllGuard, FunctionGuard
        from harness.parts.durability import MemoryDurability
        from harness.parts.context import BudgetedContext

        self.assertIsInstance(AllowAllGuard(), C.Guard)
        self.assertIsInstance(FunctionGuard(lambda step, state: C.GuardDecision.allow()), C.Guard)
        self.assertIsInstance(MemoryDurability(), C.Durability)
        self.assertIsInstance(BudgetedContext(), C.Context)

    def test_bad_impl_is_rejected(self):
        class NotAGuard:
            pass

        self.assertNotIsInstance(NotAGuard(), C.Guard)


class ExportTest(unittest.TestCase):
    def test_all_names_resolve(self):
        missing = [n for n in C.__all__ if not hasattr(C, n)]
        self.assertFalse(missing, f"__all__ 里有无法解析的名字：{missing}")

    def test_key_names_exported(self):
        for name in ("Guard", "Guardrail", "CheckpointStore", "MemoryStore", "Sandbox",
                     "FileSystem", "Middleware", "Hook", "Frame", "Failure", "RunStatus"):
            self.assertIn(name, C.__all__)

    def test_contracts_version(self):
        self.assertEqual(C.contracts_version, "3")


class StateTest(unittest.TestCase):
    def _state(self):
        return C.State(goal=C.Goal("t", session_id="s"), session=C.SessionRef("s"))

    def test_roundtrip(self):
        s = self._state()
        s.messages.append({"role": "user", "content": "hi"})
        raw = s.to_dict()
        back = C.State.from_dict(raw)
        self.assertEqual(back.goal.text, "t")
        self.assertEqual(back.messages, s.messages)

    def test_schema_version_present(self):
        self.assertIn("schema_version", self._state().to_dict())

    def test_state_rejects_unserializable(self):
        s = self._state()
        s.data["bad"] = object()
        with self.assertRaises(TypeError):
            s.to_dict()


class BudgetTest(unittest.TestCase):
    def test_split_never_exceeds_parent(self):
        b = C.Budget(tokens=1000, calls=10)
        child = b.split(0.3)
        self.assertLessEqual(child.tokens, b.remaining_tokens)
        self.assertLessEqual(child.calls, max(1, b.remaining_calls))
        self.assertTrue(child.owner.startswith("child:"))

    def test_exhausted(self):
        b = C.Budget(tokens=10, calls=1)
        self.assertFalse(b.exhausted)
        b.spend(tokens=10)
        self.assertTrue(b.exhausted)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
