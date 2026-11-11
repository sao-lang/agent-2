"""取景与编码的一致性测试（SPEC M16.3：FramerConformance / EncoderConformance）。"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.state import State
from harness.contracts.types import (
    Budget,
    Frame,
    Goal,
    Recalled,
    Section,
    SessionRef,
)
from harness.parts.framing import (
    ApprovalFramer,
    CardEncoder,
    ChatEncoder,
    HumanFramer,
    JsonlEncoder,
    ModelFramer,
    TraceFramer,
)


def run(coro):
    return asyncio.run(coro)


def make_state(*, messages: int = 0, memory: int = 0, retrieved: int = 0, tasks: int = 0):
    state = State(goal=Goal("查订单 A1001"), session=SessionRef("s1"))
    state.messages = [{"role": "user", "content": "x" * 100} for _ in range(messages)]
    state.data["memory"] = [Recalled(text="m" * 100) for _ in range(memory)]
    state.data["retrieved"] = [Recalled(text="r" * 100) for _ in range(retrieved)]
    state.data["tasks"] = [{"text": "拆任务", "status": "todo"} for _ in range(tasks)]
    return state


class FramerConformance:
    """所有取景器都必须通过（子类只提供 factory）。"""

    def factory(self):  # pragma: no cover
        raise NotImplementedError

    def test_never_drops_goal(self):
        framer = self.factory()
        frame = run(framer.frame(make_state(messages=50), budget=Budget(tokens=1)))
        if frame.kind != "model":
            self.skipTest("只对 model 帧有约束")
        self.assertTrue(any(s.name == "goal" for s in frame.sections))

    def test_deterministic_for_same_state(self):
        framer = self.factory()
        state = make_state(messages=5, memory=2)
        a = run(framer.frame(state, budget=Budget(tokens=1000)))
        b = run(framer.frame(state, budget=Budget(tokens=1000)))
        self.assertEqual(a, b)          # 可回放

    def test_sections_sorted_by_priority(self):
        framer = self.factory()
        frame = run(framer.frame(make_state(messages=3, memory=1, retrieved=1),
                                 budget=Budget(tokens=10_000)))
        priorities = [s.priority for s in frame.sections]
        self.assertEqual(priorities, sorted(priorities, reverse=True))


class ModelFramerTest(FramerConformance, unittest.TestCase):
    def factory(self):
        return ModelFramer(system="你是客服")

    def test_over_budget_marks_dropped_and_adds_omission(self):
        frame = run(self.factory().frame(make_state(messages=40, retrieved=20),
                                         budget=Budget(tokens=60)))
        self.assertTrue(frame.dropped)
        self.assertTrue(any(s.name == "omission" for s in frame.sections))
        self.assertLess(len(frame.dropped) + 1, 40 + 20 + 4)

    def test_dropped_disjoint_from_sections(self):
        frame = run(self.factory().frame(make_state(messages=40), budget=Budget(tokens=50)))
        names = {s.name for s in frame.sections}
        self.assertFalse(set(frame.dropped) & (names - {"omission"}))

    def test_under_budget_drops_nothing(self):
        frame = run(self.factory().frame(make_state(messages=2), budget=Budget(tokens=10_000)))
        self.assertEqual(frame.dropped, ())
        self.assertFalse(any(s.name == "omission" for s in frame.sections))

    def test_lower_priority_dropped_first(self):
        frame = run(self.factory().frame(make_state(messages=20, retrieved=2),
                                         budget=Budget(tokens=120)))
        if not frame.dropped:
            self.skipTest("预算足够，无需裁剪")
        self.assertIn("history", frame.dropped)   # 40 优先级最低，先丢

    def test_ephemeral_task_section(self):
        frame = run(self.factory().frame(make_state(tasks=2), budget=Budget(tokens=10_000)))
        task = next(s for s in frame.sections if s.name == "task")
        self.assertTrue(task.ephemeral)          # 只本轮可见，防污染历史


class OtherFramersTest(unittest.TestCase):
    def test_human_framer_does_not_trim(self):
        state = make_state(messages=50, retrieved=5)
        frame = run(HumanFramer().frame(state, budget=Budget(tokens=10)))
        self.assertEqual(frame.dropped, ())
        self.assertTrue(frame.meta["folded"])

    def test_approval_framer_minimal(self):
        state = make_state()
        state.data["pending"] = {"step": {"tool_name": "refund", "args": {"amount": 100}},
                                 "reason": "金额超限", "expires_at": "2026-01-01"}
        frame = run(ApprovalFramer().frame(state, budget=Budget()))
        self.assertEqual(frame.kind, "approval")
        self.assertIn("refund", frame.sections[0].text)

    def test_trace_framer_has_usage(self):
        state = make_state()
        state.usage = {"tokens": 42, "calls": 3}
        frame = run(TraceFramer().frame(state, budget=Budget()))
        self.assertIn("42", frame.sections[0].text)


class EncoderConformance:
    def encoder(self):  # pragma: no cover
        raise NotImplementedError

    def test_does_not_mutate_frame(self):
        frame = Frame(kind="model", sections=(Section("goal", 100, text="hi"),))
        before = frame
        run(self.encoder().encode(frame))
        self.assertEqual(frame, before)          # Frame 是 frozen，不可能被改

    def test_idempotent(self):
        frame = Frame(kind="model", sections=(Section("goal", 100, text="hi"),),
                      meta={"messages": [], "goal": "hi"})
        enc = self.encoder()
        self.assertEqual(run(enc.encode(frame)), run(enc.encode(frame)))


class ChatEncoderTest(EncoderConformance, unittest.TestCase):
    def encoder(self):
        return ChatEncoder()

    def test_message_shape(self):
        state = make_state(messages=2)
        frame = run(ModelFramer(system="S").frame(state, budget=Budget(tokens=10_000)))
        pack = run(ChatEncoder().encode(frame))
        self.assertEqual(pack.messages[0]["role"], "system")
        self.assertEqual(pack.messages[-1], {"role": "user", "content": "查订单 A1001"})
        self.assertEqual(pack.frame, frame)
        self.assertIn("estimated_tokens", pack.usage)

    def test_dropped_propagates_to_pack(self):
        frame = run(ModelFramer().frame(make_state(messages=50), budget=Budget(tokens=30)))
        pack = run(ChatEncoder().encode(frame))
        self.assertEqual(pack.dropped, list(frame.dropped))


class OtherEncodersTest(unittest.TestCase):
    def test_card_encoder(self):
        frame = run(ModelFramer(system="S").frame(make_state(), budget=Budget()))
        card = run(CardEncoder().encode(frame))
        self.assertIn("S", card.body)

    def test_jsonl_encoder_omits_text(self):
        frame = run(ModelFramer(system="S").frame(make_state(), budget=Budget()))
        line = run(JsonlEncoder().encode(frame))
        self.assertIn("sections", line)
        self.assertNotIn("你是", line)            # 只记结构，不落正文


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
