"""P1 内核件测试：四段顺序、失败语义、拓扑排序、洋葱、作用域。"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.errors import ConfigError, ValidationError
from harness.contracts.state import State
from harness.contracts.types import ActionResult, Goal, SessionRef, Step
from harness.kernel import chain, stage
from harness.kernel.scope import Namespace, RunScope


def _state() -> State:
    return State(goal=Goal("t"), session=SessionRef("s"))


def _step() -> Step:
    return Step(id="s1", tool_name="echo", args={"x": 1})


async def _echo(step: Step, state: State) -> ActionResult:
    return ActionResult(step_id=step.id, ok=True, output=f"echo:{step.args['x']}")


class FakeGate:
    def __init__(self, action: str, reason: str = "") -> None:
        self.action, self.reason = action, reason

    async def check(self, step, state):
        from harness.contracts.types import GuardDecision

        return GuardDecision(self.action, reason=self.reason, card={}, expires_in=None)


class ExplodingCheck:
    async def transform(self, step, state):
        raise ValidationError("not an int", field="args.x")


class RecordingCheck:
    def __init__(self, log):
        self.log = log

    async def transform(self, step, state):
        self.log.append("check")
        return step


class MarkerLayer:
    """记录洋葱进出顺序的层。"""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.points = frozenset({"tool_call"})
        self.log = log

    async def __call__(self, req, nxt):
        self.log.append(f"{self.name}.in")
        out = await nxt(req)
        self.log.append(f"{self.name}.out")
        return out


class StageTest(unittest.TestCase):
    def run_stage(self, **kwargs):
        return asyncio.run(stage.run_stages(_step(), _state(), terminal=_echo, **kwargs))

    def test_allow_all_runs_terminal(self):
        r = self.run_stage()
        self.assertTrue(r.ok)
        self.assertEqual(r.result.output, "echo:1")

    def test_gate_deny_short_circuits(self):
        r = self.run_stage(gate=FakeGate("deny", "no"))
        self.assertFalse(r.ok)
        self.assertEqual(r.failure.status, "refused")
        self.assertIsNone(r.result)

    def test_gate_ask_maps_to_needs_approval(self):
        r = self.run_stage(gate=FakeGate("ask", "need human"))
        self.assertEqual(r.failure.status, "needs_approval")

    def test_check_error_maps_to_refused_with_field(self):
        r = self.run_stage(checks=[ExplodingCheck()])
        self.assertEqual(r.failure.status, "refused")
        self.assertIn("args.x", r.failure.reason)

    def test_terminator_error_is_classified_once(self):
        async def boom(step, state):
            raise RuntimeError("kaboom")

        r = asyncio.run(stage.run_stages(_step(), _state(), terminal=boom))
        self.assertEqual(r.failure.status, "failed")
        self.assertEqual(r.failure.reason, "RuntimeError")
        self.assertFalse(r.failure.retryable)  # 未知异常 fail-closed

    def test_wrap_is_onion(self):
        log: list[str] = []
        r = self.run_stage(checks=[RecordingCheck(log)], layers=[
            MarkerLayer("outer", log), MarkerLayer("inner", log),
        ])
        self.assertTrue(r.ok)
        self.assertEqual(log, ["check", "outer.in", "inner.in", "inner.out", "outer.out"])


class ChainTest(unittest.TestCase):
    def _layer(self, name, *, points=("tool_call",), after=(), before=()):
        class L:
            pass

        lay = L()
        lay.name = name
        lay.points = frozenset(points)
        lay.after = frozenset(after)
        lay.before = frozenset(before)
        return lay

    def test_filters_by_point(self):
        a = self._layer("a")
        b = self._layer("b", points=("model_call",))
        self.assertEqual([x.name for x in chain.resolve([a, b], "tool_call")], ["a"])

    def test_after_constraint_reorders(self):
        a = self._layer("a", after=("b",))
        b = self._layer("b")
        self.assertEqual(chain.describe([a, b], "tool_call"), "b > a")

    def test_before_constraint_reorders(self):
        a = self._layer("a", before=("b",))
        b = self._layer("b")
        self.assertEqual(chain.describe([a, b], "tool_call"), "a > b")

    def test_cycle_raises_config_error(self):
        a = self._layer("a", after=("b",))
        b = self._layer("b", after=("a",))
        with self.assertRaises(ConfigError):
            chain.resolve([a, b], "tool_call")

    def test_duplicate_names_raise(self):
        with self.assertRaises(ConfigError):
            chain.resolve([self._layer("a"), self._layer("a")], "tool_call")

    def test_unknown_point_raises(self):
        with self.assertRaises(ConfigError):
            chain.resolve([], "nowhere")

    def test_execute_wraps_in_order(self):
        log: list[str] = []

        async def terminal(req):
            log.append("terminal")
            return "ok"

        asyncio.run(chain.execute([MarkerLayer("m1", log), MarkerLayer("m2", log)], None, terminal))
        self.assertEqual(log, ["m1.in", "m2.in", "terminal", "m2.out", "m1.out"])


class ScopeTest(unittest.TestCase):
    def test_child_changes_agent_and_depth(self):
        scope = RunScope(namespace=Namespace(user="u"))
        child = scope.child("worker")
        self.assertEqual(child.namespace.agent, "worker")
        self.assertEqual(child.namespace.user, "u")   # 其余三段继承
        self.assertEqual(child.depth, 1)
        self.assertEqual(scope.depth, 0)              # 父不可变

    def test_depth_limit_raises(self):
        scope = RunScope(max_depth=0)
        with self.assertRaises(ConfigError):
            scope.child("deep")

    def test_child_splits_budget(self):
        from harness.parts.budget import Budget

        parent = Budget(tokens=1000, calls=10)
        child = RunScope(budget=parent).child("w", budget_fraction=0.3)
        self.assertLessEqual(child.budget.tokens, parent.tokens)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
