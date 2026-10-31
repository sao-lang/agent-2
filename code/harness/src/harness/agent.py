"""Agent：唯一的循环内核。

它只做四件事：取下一步、过 Guard、执行、记账；策略与组件都不在这里实现。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from typing import Any

from .actor import Actor
from .budget import Budget
from .contracts import (
    ApprovalRequest,
    Decision,
    Done,
    GuardDecision,
    RunContext,
    RunStatus,
    SessionRef,
    Step,
)
from .delivery import DefaultDelivery
from .durability import NullDurability
from .errors import ApprovalExpired, ContractError, HarnessError
from .guard import AllowAllGuard
from .reflector import NullReflector
from .result import RunResult
from .state import State
from .tracer import NullTracer, new_event


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

    async def resume(self, session_id: str, decision: Decision) -> RunResult:
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

    def resume_sync(self, session_id: str, decision: Decision) -> RunResult:
        return asyncio.run(self.resume(session_id, decision))

    async def _loop(self, state: State) -> RunResult:
        start = int(time.time() * 1000)
        await self.tracer.emit(new_event(state.trace_id, "run.start", fields={
            "agent": self.name,
            "goal": state.goal.text,
        }))
        try:
            result = await self._loop_inner(state)
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

    async def _loop_inner(self, state: State) -> RunResult:
        ctx = RunContext(
            state=state,
            actor=self.actor,
            context=self.context,
            budget=self.budget,
            tracer=self.tracer,
            config=None,
        )

        while state.step_index < self.max_steps:
            if self.budget is not None and self.budget.exhausted:
                return await self.delivery.finish(
                    state, RunStatus.DEGRADED,
                    answer=state.data.get("last_output", ""),
                    error="budget exhausted",
                )

            approved = state.data.pop("_approved_step", None)
            if approved:
                step = Step(**approved)
                skip_guard = True
            else:
                decision = await self.policy.next_step(state, ctx)
                if isinstance(decision, Done):
                    return await self.delivery.finish(
                        state, RunStatus.COMPLETED, answer=decision.answer
                    )
                if not isinstance(decision, Step):
                    raise ContractError(f"BodyPolicy 返回了非法类型：{type(decision)!r}")
                step = decision
                skip_guard = False

            if not skip_guard:
                verdict: GuardDecision = await self.guard.check(step, state)
                if verdict.action == "deny":
                    return await self.delivery.finish(
                        state, RunStatus.REFUSED, error=verdict.reason
                    )
                if verdict.action == "ask":
                    pending = ApprovalRequest(
                        id=uuid.uuid4().hex[:12],
                        step=step,
                        reason=verdict.reason,
                        card=verdict.card,
                        expires_at=_expires_at(verdict.expires_in),
                        session_id=state.session.session_id,
                    )
                    state.data["pending"] = asdict(pending)
                    await self.durability.save(state)
                    return await self.delivery.finish(
                        state, RunStatus.NEEDS_APPROVAL, pending=pending
                    )

            await self.tracer.emit(new_event(
                state.trace_id, "step.start", fields={
                    "step": step.id,
                    "tool": step.tool_name or "",
                    "step_index": state.step_index,
                },
            ))
            result = await self.actor.execute(step, state)
            state.add_usage(tokens=result.tokens, calls=1)
            state.step_index += 1
            state.data["last_output"] = result.output

            if result.tool_name:
                self._append_tool_messages(state, step, result.ok, result.output, result.error)

            if result.ok:
                review = await self.reflector.review(result, state)
                if review.action == "retry":
                    state.data["_retry"] = True
                    await self.durability.save(state)
                    continue

            if not result.ok:
                state.last_error = result.error
                # 工具错误回灌给模型，让下一轮有机会修正；工作流没有模型时直接失败。
                if isinstance(self.policy, object) and self.policy.__class__.__name__ == "WorkflowPolicy":
                    return await self.delivery.finish(
                        state, RunStatus.FAILED, error=result.error
                    )

            await self.durability.save(state)
            await self.tracer.emit(new_event(
                state.trace_id, "step.end", fields={
                    "step": step.id,
                    "ok": result.ok,
                    "tokens": result.tokens,
                    "step_index": state.step_index,
                },
            ))

        return await self.delivery.finish(
            state, RunStatus.DEGRADED,
            answer=state.data.get("last_output", ""),
            error="max steps exceeded",
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


def _expires_at(seconds: int | None) -> str:
    if not seconds:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
