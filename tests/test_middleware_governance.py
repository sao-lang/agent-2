"""审批 / 幂等 / 校验 / 任务板四层的测试（P4 中段验收）。"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.approval_errors import ApprovalRequired
from harness.contracts.state import State
from harness.contracts.types import (
    ActionResult,
    Budget,
    Decision,
    Goal,
    Namespace,
    SessionRef,
    Step,
    StepRequest,
    StepResponse,
    ToolRequest,
    ToolResponse,
    ToolResult,
    ToolSpec,
    Verdict,
)
from harness.impl.backends import MemoryApprovalChannel
from harness.impl.stores import MemoryIdempotency
from harness.kernel import stage
from harness.kernel.chain import execute
from harness.parts.middleware import (
    add_task,
    approval_layer,
    idempotency_layer,
    list_tasks,
    taskboard_layer,
    update_task,
    validate_layer,
)

NS = Namespace(tenant="t1", user="u1", session="s1", agent="a")


def run(coro):
    return asyncio.run(coro)


def make_state() -> State:
    return State(goal=Goal("退款", session_id="s1"), session=SessionRef("s1"))


def spec(name: str, side: str = "pure", *, needs: bool = False, idempotent: bool = False):
    from harness.contracts.status import SideEffect

    return ToolSpec(name=name, side_effects=SideEffect(side), needs_approval=needs,
                    idempotent=idempotent)


class ApprovalLayerTest(unittest.TestCase):
    def _terminal(self, log):
        async def terminal(req):
            log.append("executed")
            return ToolResponse(result=ToolResult(step_id=req.step.id, tool=req.step.tool_name or ""))

        return terminal

    def test_pure_tool_passes_without_approval(self):
        log = []
        req = ToolRequest(step=Step(id="s1", tool_name="read"), spec=spec("read", "read"))
        run(execute([approval_layer()], req, self._terminal(log)))
        self.assertEqual(log, ["executed"])

    def test_write_tool_raises_approval_required(self):
        log = []
        req = ToolRequest(step=Step(id="s1", tool_name="refund", args={"amount": 100}),
                          spec=spec("refund", "write"))
        with self.assertRaises(ApprovalRequired) as ctx:
            run(execute([approval_layer()], req, self._terminal(log)))
        self.assertEqual(log, [])                     # 拒绝即短路，绝不执行
        self.assertEqual(ctx.exception.tool, "refund")
        self.assertIn("args", ctx.exception.card)

    def test_needs_approval_flag_wins_over_side_effects(self):
        log = []
        req = ToolRequest(step=Step(id="s1", tool_name="peek"), spec=spec("peek", "read", needs=True))
        with self.assertRaises(ApprovalRequired):
            run(execute([approval_layer()], req, self._terminal(log)))

    def test_channel_approve_proceeds(self):
        log = []

        async def terminal(req):
            log.append(req.step.args)
            return ToolResponse(result=ToolResult(step_id=req.step.id))

        channel = MemoryApprovalChannel()
        original_request = channel.request

        async def auto_approve(req):
            approval_id = await original_request(req)
            await channel.respond(approval_id, Decision.approve("alice", "ok"))
            return approval_id

        channel.request = auto_approve  # type: ignore[assignment]

        req = ToolRequest(step=Step(id="s1", tool_name="refund", args={"amount": 100}),
                          spec=spec("refund", "write"))
        run(execute([approval_layer(channel=channel, timeout_s=1)], req, terminal))
        self.assertEqual(log, [{"amount": 100}])

    def test_channel_modify_rewrites_args(self):
        log = []

        async def terminal(req):
            log.append(req.step.args)
            return ToolResponse(result=ToolResult(step_id=req.step.id))

        channel = MemoryApprovalChannel()
        original_request = channel.request

        async def modify(req):
            approval_id = await original_request(req)
            await channel.respond(approval_id, Decision.modify({"amount": 10}, "alice"))
            return approval_id

        channel.request = modify  # type: ignore[assignment]

        req = ToolRequest(step=Step(id="s1", tool_name="refund", args={"amount": 999}),
                          spec=spec("refund", "write"))
        run(execute([approval_layer(channel=channel, timeout_s=1)], req, terminal))
        self.assertEqual(log, [{"amount": 10}])      # 人改过的参数生效

    def test_reject_raises_policy_error(self):
        from harness.contracts.errors import PolicyError

        async def terminal(req):  # pragma: no cover
            return ToolResponse()

        channel = MemoryApprovalChannel()
        original_request = channel.request

        async def reject(req):
            approval_id = await original_request(req)
            await channel.respond(approval_id, Decision.reject("alice", "额度不够"))
            return approval_id

        channel.request = reject  # type: ignore[assignment]

        req = ToolRequest(step=Step(id="s1", tool_name="refund"), spec=spec("refund", "write"))
        with self.assertRaises(PolicyError):
            run(execute([approval_layer(channel=channel, timeout_s=1)], req, terminal))


class ClassifyApprovalTest(unittest.TestCase):
    def test_approval_required_maps_to_needs_approval(self):
        async def terminal(step, state):
            raise ApprovalRequired("s1", reason="side_effects=write", tool="refund")

        result = run(stage.run_stages(Step(id="s1", tool_name="refund"), make_state(),
                                      terminal=terminal))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.status, "needs_approval")
        self.assertFalse(result.failure.retryable)


class IdempotencyLayerTest(unittest.TestCase):
    def test_second_call_replays_recorded_result(self):
        store = MemoryIdempotency()
        log = []

        async def terminal(req):
            log.append(req.step.args["n"])
            return ToolResponse(result=ToolResult(step_id=req.step.id, output=f"out{req.step.args['n']}"))

        layer = idempotency_layer(store=store, ns=NS)
        step = Step(id="s1", tool_name="charge", args={"n": 1}, index=0)
        req = ToolRequest(step=step, spec=spec("charge", "write", idempotent=True))

        first = run(execute([layer], req, terminal))
        second = run(execute([layer], req, terminal))

        self.assertEqual(log, [1])                    # 副作用只发生一次
        self.assertEqual(second.result.output, first.result.output)

    def test_different_args_get_different_keys(self):
        from harness.parts.middleware import default_idem_key

        a = ToolRequest(step=Step(id="s1", tool_name="t", args={"n": 1}))
        b = ToolRequest(step=Step(id="s1", tool_name="t", args={"n": 2}))
        self.assertNotEqual(default_idem_key(a, NS), default_idem_key(b, NS))


class ValidateLayerTest(unittest.TestCase):
    def test_retry_reruns_step_then_accepts(self):
        attempts = {"n": 0}

        async def terminal(req):
            attempts["n"] += 1
            return StepResponse(step=req.step)

        class OnceReflector:
            def __init__(self):
                self.calls = 0

            async def review(self, result, state):
                self.calls += 1
                if self.calls == 1:
                    return Verdict(passed=False, reason="too short", action="retry")
                return Verdict(passed=True)

        budget = Budget()
        layer = validate_layer(reflector=OnceReflector(), max_retries=2, budget=budget)
        req = StepRequest(state=make_state(), step=Step(id="s1"))
        run(execute([layer], req, terminal))

        self.assertEqual(attempts["n"], 2)            # 重跑了一次
        self.assertEqual(budget.retries, 1)           # 计数落在预算上，不落 State

    def test_accept_does_not_retry(self):
        attempts = {"n": 0}

        async def terminal(req):
            attempts["n"] += 1
            return StepResponse(step=req.step)

        class OkReflector:
            async def review(self, result, state):
                return Verdict(passed=True)

        layer = validate_layer(reflector=OkReflector())
        run(execute([layer], StepRequest(state=make_state(), step=Step(id="s1")), terminal))
        self.assertEqual(attempts["n"], 1)


class TaskBoardLayerTest(unittest.TestCase):
    def test_layer_initialises_board(self):
        async def terminal(req):
            return StepResponse(step=req.step)

        state = make_state()
        run(execute([taskboard_layer()], StepRequest(state=state, step=Step(id="s1")), terminal))
        self.assertIn("items", state.section("tasks"))

    def test_three_tool_helpers(self):
        state = make_state()
        task = add_task(state, "查订单")
        self.assertEqual(task["status"], "todo")
        update_task(state, task["id"], "doing")
        self.assertEqual(list_tasks(state)[0]["status"], "doing")
        update_task(state, task["id"], "blocked", reason="缺权限")
        self.assertEqual(list_tasks(state)[0]["reason"], "缺权限")

    def test_task_cap(self):
        state = make_state()
        for i in range(50):
            add_task(state, f"t{i}")
        with self.assertRaises(ValueError):
            add_task(state, "over")

    def test_invalid_status_rejected(self):
        state = make_state()
        task = add_task(state, "x")
        with self.assertRaises(ValueError):
            update_task(state, task["id"], "weird")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
