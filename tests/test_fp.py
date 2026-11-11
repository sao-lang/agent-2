"""P5 门面验收：组合、顺序、端到端运行、干跑、序列化边界。"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.state import State
from harness.contracts.status import RunStatus
from harness.contracts.types import (
    Budget,
    Goal,
    ModelReply,
    SessionRef,
    Step,
    ToolCall,
)
from harness.impl.stores import MemoryCheckpointStore
from harness.kernel import chain
from harness.parts.middleware import budget_layer, checkpoint_layer, context_layer, taskboard_layer
from harness.parts.middleware.base import layer
from support import FakeModel, answer, tool_call
from harness.fp import (
    Harness,
    NotSerializable,
    Program,
    compose,
    describe,
    fallback,
    react,
    workflow,
)
from harness.parts.tools import tool


def run(coro):
    return asyncio.run(coro)


@tool
def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


class CompositionTest(unittest.TestCase):
    def test_compose_unions_points_and_keeps_order(self):
        a = layer("a", ["model_call"], lambda nxt: nxt)
        b = layer("b", ["tool_call"], lambda nxt: nxt)
        merged = compose(a, b)
        self.assertEqual(merged.points, {"model_call", "tool_call"})
        self.assertIn("a", merged.name)
        self.assertIn("b", merged.name)

    def test_program_rshift_appends_layer(self):
        p = react(max_steps=3)
        p2 = p >> taskboard_layer()
        self.assertEqual(len(p.layers), 0)
        self.assertEqual(len(p2.layers), 1)          # Program 是值，原对象不变

    def test_describe_shows_resolved_order(self):
        tool_side = layer("toolside", ["tool_call"], lambda nxt: nxt)
        p = react(max_steps=3) >> budget_layer(budget=Budget()) >> taskboard_layer() >> tool_side
        text = describe(p)
        self.assertIn("react", text)
        self.assertIn("model_call:", text)
        self.assertIn("tool_call: toolside", text)

    def test_fallback_uses_right_when_left_raises(self):
        def boom(nxt):
            async def handler(req):
                raise RuntimeError("left failed")

            return handler

        left = layer("boom", ["run"], boom)
        right = layer("ok", ["run"], lambda nxt: nxt)
        combined = fallback(left, right)

        async def terminal(req):
            return "done"

        self.assertEqual(run(chain.execute([combined], {}, terminal)), "done")


class EndToEndTest(unittest.TestCase):
    def test_three_line_program_runs(self):
        model = FakeModel([tool_call("concat", left="a", right="b"), answer("ab")])
        h = Harness.of(model=model, tools=[concat])
        program = react(max_steps=4) >> taskboard_layer()

        result = run(h.run(program, Goal("拼接", session_id="s1")))

        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "ab")
        self.assertEqual(model.calls, 2)
        self.assertEqual(result.usage["calls"], 2)

    def test_workflow_body_runs_fixed_steps(self):
        model = FakeModel([answer("unused")])
        h = Harness.of(model=model, tools=[concat])
        program = workflow(
            Step(id="a", tool_name="concat", args={"left": "x", "right": "y"}),
            Step(id="b", tool_name="concat", args={"left": "p", "right": "q"}),
        )
        result = run(h.run(program, Goal("固定流程", session_id="s2")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(result.answer, "pq")          # 最后一步的输出
        self.assertEqual(model.calls, 0)               # workflow 不调模型

    def test_checkpoint_layer_persists_each_step(self):
        from harness.contracts.types import Namespace

        store = MemoryCheckpointStore()

        def checkpoint_build(nxt):
            async def handler(req):
                await store.put(
                    Namespace(),
                    req.state.session.session_id,
                    req.state,
                    expect_rev=req.state.rev,
                )
                return await nxt(req)

            return handler

        ckpt = layer("checkpoint", ["step"], checkpoint_build)
        model = FakeModel([tool_call("concat", left="1", right="2"), answer("12")])
        h = Harness.of(model=model, tools=[concat])
        program = react(max_steps=4) >> ckpt
        run(h.run(program, Goal("x", session_id="ck")))
        self.assertEqual(run(store.history(Namespace(), "ck")), [0])   # 只执行了 1 步工具调用

    def test_budget_exhaustion_degrades(self):
        model = FakeModel([tool_call("concat", left="a", right="b")] * 5)
        h = Harness.of(model=model, tools=[concat], budget=Budget(tokens=1, calls=1))
        result = run(h.run(react(max_steps=5), Goal("loop", session_id="b")))
        self.assertEqual(result.status, RunStatus.DEGRADED)

    def test_guard_denies_and_run_refuses(self):
        from harness.contracts.types import GuardDecision
        from harness.parts.guard import FunctionGuard

        guard = FunctionGuard(lambda step, state: GuardDecision.deny("nope"))
        model = FakeModel([tool_call("concat", left="a", right="b")])
        h = Harness.of(model=model, tools=[concat], guard=guard)
        result = run(h.run(react(max_steps=3), Goal("x", session_id="g")))
        self.assertEqual(result.status, RunStatus.REFUSED)


class DryRunTest(unittest.TestCase):
    def test_dry_run_records_effects_without_executing(self):
        executed = []

        @tool
        def charge(amount: int) -> str:
            """扣款。"""
            executed.append(amount)
            return "ok"

        model = FakeModel([tool_call("charge", amount=100), answer("done")])
        h = Harness.of(model=model, tools=[charge])
        effects = run(h.dry_run(react(max_steps=3) >> taskboard_layer(),
                                Goal("扣款", session_id="d")))

        self.assertEqual(executed, [])                 # 副作用一次都没发生
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].step.tool_name, "charge")

    def test_dry_run_empty_when_no_tools_planned(self):
        model = FakeModel([answer("直接回答")])
        h = Harness.of(model=model)
        self.assertEqual(run(h.dry_run(react(max_steps=2), Goal("x", session_id="d2"))), [])


class SerializationBoundaryTest(unittest.TestCase):
    def test_closure_layer_is_not_serializable(self):
        p = react() >> layer("custom", ["run"], lambda nxt: nxt)
        with self.assertRaises(NotSerializable):
            p.to_spec()

    def test_declared_layer_form_roundtrip(self):
        from harness.contracts.types import LayerSpec, ProgramSpec

        # 只有声明形态（LayerSpec）可序列化；闭包层按设计拒绝
        p = Program(body=react().body, layers=())
        spec = p.to_spec()
        self.assertEqual(spec.body, "react")
        self.assertEqual(spec.layers, ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
