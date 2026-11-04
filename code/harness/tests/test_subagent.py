"""子 agent 与五个薄层的测试（P4 后段验收之二）。"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.errors import ConfigError
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.types import (
    Budget,
    Goal,
    ModelRequest,
    RunRequest,
    RunStatus,
    SessionRef,
    Step,
    StepRequest,
    ToolRequest,
    ToolResponse,
    ToolResult,
)
from harness.kernel.chain import execute
from harness.kernel.scope import RunScope
from harness.parts.layers import (
    audit_layer,
    memory_recall_layer,
    memory_write_layer,
    retrieval_layer,
    tenancy_layer,
)
from harness.parts.subagent import subagent_layer


async def _noop(req):
    return None


def run(coro):
    return asyncio.run(coro)


def make_state() -> State:
    return State(goal=Goal("拆任务", session_id="s1"), session=SessionRef("s1"))


class FakeChild:
    """假子 agent：记录收到的 scope，返回固定摘要。"""

    def __init__(self, scope, task, *, answer="子结论", status=RunStatus.COMPLETED, delay=0.0):
        self.scope, self.task, self.answer, self.status, self.delay = scope, task, answer, status, delay

    async def run(self, goal, *, scope=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        return RunResult(
            status=self.status,
            answer=self.answer,
            usage={"tokens": 7, "calls": 1},
        )


class SubAgentTest(unittest.TestCase):
    def _layer(self, scope, factory, **kw):
        return subagent_layer(scope=scope, agent_factory=factory, **kw)

    def test_task_tool_spawns_child_with_summary_only(self):
        created = []

        def factory(scope, task):
            child = FakeChild(scope, task)
            created.append(child)
            return child

        scope = RunScope(budget=Budget(tokens=1000, calls=10))
        layer = self._layer(scope, factory)
        req = ToolRequest(step=Step(id="s1", tool_name="task", args={"description": "查订单"}))
        out = run(execute([layer], req, _noop))

        self.assertTrue(out.result.ok)
        self.assertEqual(out.result.output, "子结论")
        self.assertEqual(out.result.meta["depth"], 1)
        self.assertEqual(out.result.meta["usage"]["tokens"], 7)
        self.assertEqual(created[0].task.description, "查订单")

    def test_child_scope_has_split_budget_and_new_namespace(self):
        captured = {}

        def factory(scope, task):
            captured["scope"] = scope
            return FakeChild(scope, task)

        scope = RunScope(namespace=__import__("harness.kernel.scope", fromlist=["Namespace"]).Namespace(agent="root"),
                         budget=Budget(tokens=1000, calls=10))
        layer = self._layer(scope, factory, budget_fraction=0.3)
        req = ToolRequest(step=Step(id="s1", tool_name="task", args={"description": "x"}))
        run(execute([layer], req, _noop))

        child = captured["scope"]
        self.assertEqual(child.namespace.agent, "default")     # 新 agent 名
        self.assertEqual(child.namespace.session, scope.namespace.session)  # 其余继承
        self.assertLessEqual(child.budget.tokens, scope.budget.remaining_tokens)

    def test_depth_limit_raises(self):
        def factory(scope, task):
            return FakeChild(scope, task)

        scope = RunScope(max_depth=0)
        layer = self._layer(scope, factory)
        req = ToolRequest(step=Step(id="s1", tool_name="task", args={"description": "x"}))
        with self.assertRaises(ConfigError):
            run(execute([layer], req, _noop))

    def test_missing_description_rejected(self):
        scope = RunScope()
        layer = self._layer(scope, lambda s, t: FakeChild(s, t))
        req = ToolRequest(step=Step(id="s1", tool_name="task", args={}))
        out = run(execute([layer], req, _noop))
        self.assertFalse(out.result.ok)
        self.assertIn("description", out.result.error)

    def test_concurrency_cap_serialises(self):
        """并发上限 1 时，三个子运行必须串行（峰值并发 = 1）。"""
        meter = {"now": 0, "peak": 0}

        class SlowChild(FakeChild):
            async def run(self, goal, *, scope=None):
                meter["now"] += 1
                meter["peak"] = max(meter["peak"], meter["now"])
                try:
                    await asyncio.sleep(0.02)
                    return RunResult(status=RunStatus.COMPLETED, answer="ok")
                finally:
                    meter["now"] -= 1

        scope = RunScope()
        layer = self._layer(scope, lambda s, t: SlowChild(s, t), concurrency=1)

        async def scenario():
            req = ToolRequest(step=Step(id="s1", tool_name="task", args={"description": "x"}))
            await asyncio.gather(*(execute([layer], req, _noop) for _ in range(3)))

        run(scenario())
        self.assertEqual(meter["peak"], 1)

    def test_other_tools_pass_through(self):
        scope = RunScope()
        seen = []

        def factory(s, t):  # pragma: no cover - 不应被调用
            raise AssertionError("不该创建子 agent")

        layer = self._layer(scope, factory)

        async def terminal(req):
            seen.append(req.step.tool_name)
            return ToolResponse(result=ToolResult(step_id="s1", tool="other", ok=True))

        run(execute([layer], ToolRequest(step=Step(id="s1", tool_name="other")), terminal))
        self.assertEqual(seen, ["other"])


class ThinLayersTest(unittest.TestCase):
    def test_tenancy_rejects_foreign_tenant(self):
        from harness.contracts.errors import PolicyError
        from harness.contracts.types import Namespace

        layer = tenancy_layer(expected_tenant="t1")
        req = RunRequest(goal=Goal("x"), ns=Namespace(tenant="t2"))
        with self.assertRaises(PolicyError):
            run(execute([layer], req, _noop))

    def test_audit_emits_and_never_breaks(self):
        events = []

        class Sink:
            async def emit(self, e):
                events.append(e)

        layer = audit_layer(sink=Sink())

        async def tool_ok(req):
            return ToolResponse(result=ToolResult(step_id="s1", tool="t", ok=True))

        run(execute([layer], ToolRequest(step=Step(id="s1", tool_name="t")), tool_ok))
        self.assertEqual(events[0].name, "audit")
        self.assertTrue(events[0].fields["ok"])

    def test_audit_sink_failure_is_swallowed(self):
        class Broken:
            async def emit(self, e):
                raise RuntimeError("down")

        layer = audit_layer(sink=Broken())

        async def tool_ok(req):
            return ToolResponse(result=ToolResult(step_id="s1", ok=True))

        out = run(execute([layer], ToolRequest(step=Step(id="s1", tool_name="t")), tool_ok))
        self.assertTrue(out.result.ok)

    def test_retrieval_populates_once(self):
        from harness.contracts.types import Recalled

        calls = []

        class KB:
            async def retrieve(self, query, *, k, filters=None):
                calls.append(query)
                return [Recalled(text="doc", score=0.9)]

        layer = retrieval_layer(knowledge=KB(), k=3)
        state = make_state()
        req = ModelRequest(state=state)

        async def twice():
            await execute([layer], req, _noop)
            await execute([layer], req, _noop)

        run(twice())
        self.assertEqual(len(calls), 1)                 # 一轮只检索一次
        self.assertEqual(state.data["retrieved"][0].text, "doc")

    def test_memory_recall_and_write(self):
        from harness.contracts.types import Recalled

        class Mem:
            def __init__(self):
                self.recalled, self.written = [], []

            async def recall(self, query, *, scope, layers, k):
                self.recalled.append(query)
                return [Recalled(text="记得的事")]

            async def write(self, items):
                self.written.extend(items)
                return len(items)

        class Policy:
            async def should_write(self, state, result):
                state.data["last_output"] = "结论"
                return True

            async def extract(self, state):
                return [Recalled(text=state.data.get("last_output", ""), source="run:x")]

        memory = Mem()
        recall = memory_recall_layer(memory=memory)
        write = memory_write_layer(memory=memory, policy=Policy())

        state = make_state()

        async def scenario():
            await execute([recall], ModelRequest(state=state), _noop)

            async def finish(req):
                return RunResult(status=RunStatus.COMPLETED, answer="ok")

            await execute([write], RunRequest(goal=state.goal, state=state), finish)

        run(scenario())
        self.assertEqual(memory.recalled, ["拆任务"])
        self.assertEqual(memory.written[0].text, "结论")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
