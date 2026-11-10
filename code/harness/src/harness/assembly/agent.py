"""Agent：v1 兼容壳（PROPOSAL §9.3 / §10）。

**这里不再有循环。** 名字、构造参数、``run / run_sync / resume / resume_sync``
签名与 ``RunResult`` 语义全部保留；循环体已删除，改由
``kernel.interpret.Runtime.interpret`` 驱动 —— 全框架唯一循环。

旧路径的逐步语义（Guard 审批、Actor 执行、消息回灌、Reflector 重试、
Durability 存档、Tracer 事件）由注入的 ``CallbackRunner`` 与
``after_commit`` 钩子复现，解释器本身不认识任何 v1 概念。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from typing import Any

from harness.contracts.decision import Decision, Halt
from harness.contracts.errors import ApprovalExpired, ContractError, HarnessError
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.status import RunStatus
from harness.contracts.types import (
    ApprovalRequest,
    Decision as ApprovalDecision,
    Done,
    Effect,
    GuardDecision,
    RunContext,
    SessionRef,
    Step,
)
from harness.kernel.effects import CallbackRunner
from harness.kernel.interpret import Limits, Runtime, Outcome
from harness.parts.actor import Actor
from harness.parts.budget import Budget
from harness.parts.delivery import DefaultDelivery
from harness.parts.durability import NullDurability
from harness.parts.guard import AllowAllGuard
from harness.parts.reflector import NullReflector
from harness.parts.tracer import NullTracer, new_event


class Agent:
    name = "agent"

    def __init__(
        self,
        *,
        policy,
        actor: Actor,
        context,
        guard=None,
        budget=None,
        tracer=None,
        durability=None,
        delivery=None,
        reflector=None,
        max_steps: int = 24,
        name: str = "agent",
        knowledge=None,
        retrieval=None,
        memory=None,
        memory_policy=None,
        limits=None,
        checkpoints=None,
    ) -> None:
        self.policy = policy
        self.actor = actor
        self.context = context
        self.guard = guard or AllowAllGuard()
        self.budget = budget or Budget()
        self.tracer = tracer or NullTracer()
        self.durability = durability or NullDurability()
        self.delivery = delivery or DefaultDelivery()
        self.reflector = reflector or NullReflector()
        self.max_steps = max_steps
        self.name = name
        # v3.1（SUPPLEMENT A4）：显式 limits 优先；缺省由 Budget 推导——
        # 预算耗尽由解释器护栏触发（degraded），程序不再自查（消灭双重计数）。
        self.limits = limits
        # v3.1（SUPPLEMENT A2）：检查点存储（CheckpointStore 协议），供崩溃恢复。
        self.checkpoints = checkpoints
        self.knowledge = knowledge
        self.retrieval = retrieval
        self.memory = memory
        self.memory_policy = memory_policy

    async def run(self, goal, session: SessionRef | None = None) -> RunResult:
        session = session or SessionRef(
            session_id=goal.session_id,
            tenant=str(goal.metadata.get("tenant", "default")),
        )
        state = State(goal=goal, session=session)
        await self._prepare(state)
        return await self._loop(state)

    def run_sync(self, goal, session: SessionRef | None = None) -> RunResult:
        """同步包装；在已有事件循环里不要调用它。"""
        return asyncio.run(self.run(goal, session))

    async def _prepare(self, state: State) -> None:
        if self.memory is not None and self.memory_policy is not None:
            state.data["memory"] = await self.memory.recall(
                state.goal.text,
                scope=state.goal.user_id,
                layers=list(self.memory_policy.get("layers", ["semantic", "episodic"])),
                k=int(self.memory_policy.get("k", 6)),
            )
        if self.knowledge is not None and self.retrieval is not None:
            state.data["retrieved"] = await self.retrieval.retrieve(
                state.goal, self.knowledge, tenant=state.session.tenant
            )

    async def resume(self, session_id: str, decision: ApprovalDecision | None = None,
                     *, rev: int | None = None, ns: Any = None) -> RunResult:
        """恢复运行（SUPPLEMENT A2）。

        decision=None 且配置了 checkpoints → 崩溃恢复：按 session_id + rev
        取最近（或指定）检查点，重放续跑。恢复是重放结论不是重新推理；
        已生效副作用靠幂等键保证不重复。闭包策略不可序列化，policy 由
        本 Agent 现场重供给。ns 须与产生检查点时的租户/用户一致。
        """
        if decision is None:
            return await self._resume_from_checkpoint(session_id, rev=rev, ns=ns)

        state = await self.durability.load(session_id)
        if state is None:
            raise HarnessError(f"没有可恢复的 session：{session_id}")

        pending_raw = state.data.get("pending")
        if not pending_raw:
            raise HarnessError(f"session {session_id} 没有待审批项")
        pending = self._pending_from_dict(pending_raw)
        if pending.expires_at and pending.expires_at < _now_iso():
            state.data.pop("pending", None)
            await self.durability.save(state)
            raise ApprovalExpired(f"审批已过期：{pending.id}")

        if decision.action == "reject":
            state.data.pop("pending", None)
            state.status = RunStatus.REFUSED
            await self.durability.save(state)
            return await self.delivery.finish(
                state, RunStatus.REFUSED, answer="", error=decision.reason or "rejected"
            )

        if decision.action == "modify":
            pending.step = Step(
                id=pending.step.id,
                instruction=pending.step.instruction,
                tool_name=pending.step.tool_name,
                args={**pending.step.args, **decision.args},
                idem_key=pending.step.idem_key,
                kind=pending.step.kind,
            )

        state.data.pop("pending", None)
        state.data["_approved_step"] = asdict(pending.step)
        state.data["_approved_by"] = decision.by
        return await self._loop(state)

    async def _resume_from_checkpoint(self, session_id: str, *, rev: int | None = None,
                                      ns: Any = None) -> RunResult:
        """崩溃恢复路径（SUPPLEMENT A2）：从检查点重放，不重新推理。"""
        if self.checkpoints is None:
            raise HarnessError("Agent 未配置 checkpoints 存储，无法做崩溃恢复")
        from harness.contracts.types import Namespace

        ns = ns or Namespace()
        checkpoint = await self.checkpoints.get(ns, session_id, rev)
        if checkpoint is None:
            raise HarnessError(f"没有可恢复的检查点：{session_id}"
                               + (f"@rev{rev}" if rev is not None else ""))
        state = checkpoint.state
        if not isinstance(state, State):
            raise HarnessError("检查点里的 state 形状不合法")
        return await self._loop(state)

    def resume_sync(self, session_id: str, decision: ApprovalDecision | None = None,
                    **kwargs: Any) -> RunResult:
        return asyncio.run(self.resume(session_id, decision, **kwargs))

    # ---------------------------------------------------------------- 兼容壳

    async def _loop(self, state: State) -> RunResult:
        start = int(time.time() * 1000)
        await self.tracer.emit(new_event(state.trace_id, "run.start", fields={
            "agent": self.name,
            "goal": state.goal.text,
        }))
        try:
            result = await self._interpret(state)
        except Exception as exc:  # noqa: BLE001 - 运行边界
            state.status = RunStatus.FAILED
            state.last_error = str(exc)
            result = await self.delivery.finish(state, RunStatus.FAILED, error=str(exc))
        await self.tracer.emit(new_event(
            state.trace_id, "run.end", start_ms=start,
            end_ms=int(time.time() * 1000),
            fields={"status": str(result.status), "steps": state.step_index},
        ))
        return result

    async def _interpret(self, state: State) -> RunResult:
        """v1 语义编译成 ``transition``，交给唯一解释器。"""
        ctx = RunContext(
            state=state, actor=self.actor, context=self.context, budget=self.budget,
            tracer=self.tracer, config=None,
        )

        async def run_one(effect: Effect, st: State) -> dict[str, Any]:
            step = effect.step
            skip_guard = bool(effect.args.get("skip_guard", False))
            if not skip_guard:
                verdict: GuardDecision = await self.guard.check(step, st)
                if verdict.action == "deny":
                    return _halt_result("refused", "", reason=verdict.reason)
                if verdict.action == "ask":
                    pending = ApprovalRequest(
                        id=uuid.uuid4().hex[:12],
                        step=step,
                        reason=verdict.reason,
                        card=verdict.card,
                        expires_at=_expires_at(verdict.expires_in),
                        session_id=st.session.session_id,
                    )
                    st.data["pending"] = asdict(pending)
                    await self.durability.save(st)
                    return _halt_result("needs_approval", "", pending=pending)

            await self.tracer.emit(new_event(
                st.trace_id, "step.start", fields={
                    "step": step.id, "tool": step.tool_name or "",
                    "step_index": st.step_index,
                },
            ))
            result = await self.actor.execute(step, st)
            st.data["last_output"] = result.output
            if result.tool_name:
                self._append_tool_messages(st, step, result.ok, result.output, result.error)

            if result.ok:
                review = await self.reflector.review(result, st)
                if review.action == "retry":
                    st.data["_retry"] = True
                    await self.durability.save(st)
                    return {"ok": True, "skip_tail": True,
                            "_usage": {"calls": 1, "tokens": 0}}

            if not result.ok:
                st.last_error = result.error
                # 工具错误回灌给模型；工作流没有模型时直接失败。
                if self.policy.__class__.__name__ == "WorkflowPolicy":
                    return _halt_result("failed", "", reason=result.error)

            return {
                "ok": result.ok, "output": result.output, "raw": result,
                "tokens": int(getattr(result, "tokens", 0) or 0),
                "_usage": {"calls": 1, "tokens": 0},
                "skip_tail": False,
                "tool_name": result.tool_name,
                "error": result.error,
            }

        async def after_commit(st: State, decision: Decision, results: list) -> None:
            if not results or not isinstance(results[0], dict):
                return
            info = results[0]
            if info.get("skip_tail"):
                return
            await self.durability.save(st)
            if self.checkpoints is not None:
                # v3.1（SUPPLEMENT A2）：解释器级检查点落盘（供按 rev 重放）。
                from harness.contracts.types import Namespace

                ns = Namespace(tenant=st.session.tenant,
                               user=getattr(st.goal, "user_id", "anonymous") or "anonymous",
                               session=st.session.session_id)
                await self.checkpoints.put(ns, st.session.session_id, st,
                                           expect_rev=st.rev - 1)
            step = decision.effects[0].step if decision.effects else None
            await self.tracer.emit(new_event(
                st.trace_id, "step.end", fields={
                    "step": getattr(step, "id", ""),
                    "ok": bool(info.get("ok", False)),
                    "tokens": int(info.get("tokens", 0) or 0),
                    "step_index": st.step_index,
                },
            ))

        # v3.1（SUPPLEMENT A4）：预算统一接线——calls/tokens 护栏直接取自
        # Budget 口径，墙钟/转移数由 Limits 承担；程序不再自查预算。
        if self.limits is not None:
            limits = self.limits
        else:
            limits = Limits(max_transitions=self.max_steps + 2,
                            max_calls=self.budget.calls,
                            max_tokens=self.budget.tokens,
                            wall_seconds=300.0)
        runtime = Runtime(
            limits=limits,
            runner=CallbackRunner(run_one),
            after_commit=after_commit,
            emit=None,
        )
        out = await runtime.interpret(_V1Program(self, ctx), state)
        return await self._finish(out, state)

    async def _finish(self, out: Outcome, state: State) -> RunResult:
        try:
            status = RunStatus(out.status)
        except ValueError:
            status = RunStatus.FAILED
        state.status = status
        extra = out.extra
        reason = extra.get("reason")
        return await self.delivery.finish(
            state, status,
            answer=out.answer,
            error=(str(reason) if reason and status is not RunStatus.COMPLETED else None),
            pending=extra.get("pending"),
        )

    def _append_tool_messages(self, state: State, step: Step, ok: bool,
                              output: str, error: str | None) -> None:
        if step.tool_name is None:
            return
        state.messages.append({
            "role": "assistant",
            "content": step.instruction,
            "tool_calls": [{
                "id": step.id,
                "type": "function",
                "function": {"name": step.tool_name, "arguments": _json_dumps(step.args)},
            }],
        })
        state.messages.append({
            "role": "tool",
            "tool_call_id": step.id,
            "content": output if ok else f"ERROR: {error}",
        })

    @staticmethod
    def _pending_from_dict(raw: dict[str, Any]) -> ApprovalRequest:
        step = Step(**raw["step"])
        return ApprovalRequest(
            id=raw["id"],
            step=step,
            reason=raw.get("reason", ""),
            card=raw.get("card", {}),
            expires_at=raw.get("expires_at", ""),
            session_id=raw.get("session_id", ""),
        )


class _V1Program:
    """v1 ``BodyPolicy.next_step`` → 唯一协议 ``transition``。"""

    name = "agent_v1"

    def __init__(self, agent: Agent, ctx: RunContext) -> None:
        self.agent = agent
        self.ctx = ctx

    async def transition(self, state: State) -> Decision | Halt:
        agent = self.agent
        # v3.1（SUPPLEMENT A4）：预算自查已删除——Budget.calls/tokens 已映射进
        # 解释器 Limits，由 _guardrail 统一触发 degraded，这里不再双重计数。
        if state.step_index >= agent.max_steps:
            return Halt(state.data.get("last_output", ""), "degraded",
                        {"reason": "max steps exceeded"})

        approved = state.data.pop("_approved_step", None)
        if approved:
            step, skip_guard = Step(**approved), True
        else:
            decision = await agent.policy.next_step(state, self.ctx)
            if isinstance(decision, Done):
                return Halt(decision.answer, "completed")
            if not isinstance(decision, Step):
                raise ContractError(f"BodyPolicy 返回了非法类型：{type(decision)!r}")
            step, skip_guard = decision, False

        return Decision(
            effects=(Effect(kind="tool", step=step, key=step.id,
                            args={"skip_guard": skip_guard}),),
            program=self,
            meta={"bump_step": True},
            note=step.id,
        )


def _halt_result(status: str, answer: str = "", **extra: Any) -> dict[str, Any]:
    """Guard/失败分支：让解释器在唯一提交点之后终止，不产生副作用计量。"""
    return {
        "ok": False,
        "_halt": {"status": status, "answer": answer, "extra": extra},
        "_usage": {"calls": 0, "tokens": 0},
        "skip_tail": True,
    }


def _expires_at(seconds: int | None) -> str:
    if not seconds:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = ["Agent"]
