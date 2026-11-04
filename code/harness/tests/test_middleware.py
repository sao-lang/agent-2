"""层机制与四个内置层的测试（P4 前半验收）。"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.state import State
from harness.contracts.types import (
    Budget,
    Goal,
    ModelReply,
    ModelRequest,
    ModelResponse,
    SessionRef,
    Step,
    StepRequest,
    StepResponse,
)
from harness.impl.stores import MemoryCheckpointStore
from harness.kernel import chain
from harness.parts.middleware import (
    Layer,
    budget_layer,
    checkpoint_layer,
    context_layer,
    layer,
    trace_layer,
)


def run(coro):
    return asyncio.run(coro)


def make_state() -> State:
    state = State(goal=Goal("查 A1001", session_id="s1"), session=SessionRef("s1"))
    state.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    return state


class FakeSink:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


class LayerTest(unittest.TestCase):
    def test_layer_is_a_value(self):
        a = layer("a", ["run"], lambda nxt: nxt)
        b = layer("a", ["run"], lambda nxt: nxt)
        self.assertEqual(a, b)            # 纯值：可比较、可存库

    def test_points_filtering(self):
        l1 = layer("l1", ["run"], lambda nxt: nxt)
        l2 = layer("l2", ["step"], lambda nxt: nxt)
        self.assertEqual([x.name for x in chain.resolve([l1, l2], "run")], ["l1"])


class ContextLayerTest(unittest.TestCase):
    def test_rewrites_messages_with_frame(self):
        state = make_state()
        ctx = context_layer(system="你是客服")
        seen = {}

        async def terminal(req):
            seen["req"] = req
            return ModelResponse(reply=ModelReply(content="ok"))

        req = ModelRequest(state=state, budget=Budget(tokens=10_000))
        run(chain.execute([ctx], req, terminal))

        messages = seen["req"].messages
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("你是客服", messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "查 A1001"})
        self.assertIsNotNone(seen["req"].frame)

    def test_ignores_non_model_request(self):
        ctx = context_layer()
        captured = {}

        async def terminal(req):
            captured["req"] = req
            return StepResponse(step=Step(id="s1"))

        req = StepRequest(state=make_state(), step=Step(id="s1"))
        run(chain.execute([ctx], req, terminal))
        self.assertIs(captured["req"], req)      # 请求原样透传


class CheckpointLayerTest(unittest.TestCase):
    def test_writes_one_rev_per_step(self):
        store = MemoryCheckpointStore()
        ckpt = checkpoint_layer(store=store)
        state = make_state()

        async def terminal(req):
            return StepResponse(step=req.step)

        for i in range(2):
            state.step_index = i
            run(chain.execute([ckpt], StepRequest(state=state, step=Step(id=f"s{i}")), terminal))

        self.assertEqual(run(store.history(chain_ns(state), "s1")), [0, 1])


def chain_ns(state: State):
    from harness.parts.middleware.builtin import state_namespace

    return state_namespace(state)


class BudgetLayerTest(unittest.TestCase):
    def test_spends_on_model_response(self):
        budget = Budget(tokens=1000, calls=10)
        bl = budget_layer(budget=budget)

        async def terminal(req):
            return ModelResponse(reply=ModelReply("ok"), usage={"total": 120})

        run(chain.execute([bl], ModelRequest(state=make_state()), terminal))
        self.assertEqual(budget.used_tokens, 120)
        self.assertEqual(budget.used_calls, 1)

    def test_exhausted_raises(self):
        from harness.contracts.errors import BudgetExceeded

        budget = Budget(tokens=1, calls=1)
        budget.spend(tokens=5)
        bl = budget_layer(budget=budget)

        async def terminal(req):  # pragma: no cover
            return ModelResponse()

        with self.assertRaises(BudgetExceeded):
            run(chain.execute([bl], ModelRequest(state=make_state()), terminal))


class TraceLayerTest(unittest.TestCase):
    def test_emits_span_even_on_error(self):
        sink = FakeSink()
        tl = trace_layer(sink=sink)

        async def boom(req):
            raise RuntimeError("x")

        with self.assertRaises(RuntimeError):
            run(chain.execute([tl], ModelRequest(), boom))
        self.assertEqual(len(sink.events), 1)      # 异常也要留痕
        self.assertEqual(sink.events[0].name, "span.end")

    def test_observer_never_breaks_request(self):
        class BrokenSink:
            async def emit(self, event):
                raise RuntimeError("sink down")

        tl = trace_layer(sink=BrokenSink())

        async def terminal(req):
            return ModelResponse(reply=ModelReply("ok"))

        out = run(chain.execute([tl], ModelRequest(), terminal))
        self.assertEqual(out.reply.content, "ok")  # 观测失败不影响可用性


class OrderingTest(unittest.TestCase):
    def test_budget_runs_after_tenancy(self):
        tenancy = layer("tenancy", ["run"], lambda nxt: nxt)
        budget = budget_layer(budget=Budget())
        order = [x.name for x in chain.resolve([budget, tenancy], "run")]
        self.assertEqual(order, ["tenancy", "budget"])

    def test_context_before_input_guard(self):
        ctx = context_layer()
        guard = layer("input_guard", ["model_call"], lambda nxt: nxt)
        order = [x.name for x in chain.resolve([guard, ctx], "model_call")]
        self.assertEqual(order, ["context", "input_guard"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
