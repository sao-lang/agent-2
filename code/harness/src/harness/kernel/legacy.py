"""v2 组合子线的前端适配（PROPOSAL §9.3 / §10）。

原来的 ``kernel/loop.run_loop`` 是第二个独立循环；现在它只是一个**前端**：
把 ``Program = body + layers`` 编译成唯一协议 ``transition(state)``，
四段链、step 插点、事件、dry_run 记录由注入的 ``CallbackRunner`` 与
``after_commit`` 钩子复现，循环本身交给 ``kernel.interpret.Runtime``。

``kernel/stage.py`` 的四段链一行未改：``Effect → Step`` 薄适配器喂进去即可。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from harness.contracts.decision import Decision, Halt
from harness.contracts.errors import HarnessError
from harness.contracts.events import RunEvent
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.status import RunStatus
from harness.contracts.types import Done, Effect, Step, StepRequest, StepResponse
from harness.kernel import chain, stage
from harness.kernel.effects import CallbackRunner
from harness.kernel.interpret import Limits, Runtime, Outcome

__all__ = ["LegacyProgram", "run_legacy", "as_run_result"]


class LegacyProgram:
    """``body.next_step`` → ``transition``；鸭子类型满足新 Program 协议。"""

    name = "legacy"

    def __init__(self, program: Any, scope: Any) -> None:
        self.program = program
        self.scope = scope

    async def transition(self, state: State) -> Decision | Halt:
        if self.scope.budget is not None and self.scope.budget.exhausted:
            return Halt("", "degraded", {"reason": "budget"})
        if state.step_index >= self.program.max_steps:
            return Halt("", "degraded", {"reason": "max_steps"})
        try:
            decision = await self.program.body.next_step(state, self.scope)
        except Exception as exc:  # noqa: BLE001 - 决策失败也要归类
            failure = (await self.scope.filter.classify(exc, phase="step", state=state)
                       if self.scope.filter is not None else None)
            if failure is None:
                state.last_error = str(exc)
                return Halt("", "failed", {"reason": str(exc)})
            state.last_error = failure.reason
            return Halt("", str(failure.status), {"reason": failure.reason})

        if isinstance(decision, Done):
            return Halt(decision.answer, "completed")
        if not isinstance(decision, Step):
            raise HarnessError(f"BodyPolicy 返回非法类型：{type(decision)!r}")
        return Decision(
            effects=(Effect(kind="tool", step=decision, key=decision.id),),
            program=self,
            meta={"bump_step": True},
            note=f"step:{decision.id}",
        )


async def run_legacy(*, program: Any, state: State, scope: Any,
                     record_effects: list | None = None,
                     max_transitions: int | None = None) -> RunResult:
    """旧签名、旧行为；循环在 ``Runtime.interpret`` 里，且全框架仅此一处。"""
    from harness.contracts.types import ActionResult

    scope = replace(
        scope,
        layers=tuple(program.layers),
        model_call=_make_model_call(program, scope),
    )
    tool_layers = chain.resolve(program.layers, "tool_call")
    step_layers = chain.resolve(program.layers, "step")

    async def terminal(step: Step, st: State):
        if record_effects is not None:
            record_effects.append(Effect(kind="tool", step=step))
            return ActionResult(step_id=step.id, ok=True, output="[dry-run]")
        return await scope.actor.step(step, st, scope)

    async def run_one(effect: Effect, st: State) -> dict[str, Any]:
        step = effect.step
        await _emit(scope, st, "step.start", step=step.id, tool=step.tool_name or "")
        sr = await stage.run_stages(
            step, st, terminal=terminal, gate=scope.guard,
            checks=tuple(scope.pipes), layers=tool_layers, classify=scope.filter,
        )
        if sr.failure is not None:
            return {
                "ok": False,
                "_halt": {"status": str(sr.failure.status), "answer": "",
                          "extra": {"reason": sr.failure.reason}},
                "_usage": {"calls": 0, "tokens": 0},
            }
        ar = sr.result
        return {
            "ok": bool(getattr(ar, "ok", False)),
            "output": getattr(ar, "output", "") if ar is not None else "",
            "raw": ar,
            # LlmActor.propose() 已经记过模型调用，这里不能重复计量。
            "_usage": {"calls": 0, "tokens": 0},
        }

    async def after_commit(st: State, decision: Decision, results: list) -> None:
        step = decision.effects[0].step if decision.effects else None
        ok = bool(results and isinstance(results[0], dict) and results[0].get("ok", False))
        if step is not None:
            await _emit(scope, st, "step.end", step=step.id, ok=ok)
        if step_layers:
            await chain.execute(step_layers, StepRequest(state=st, step=step), _identity)

    await _emit(scope, state, "run.start", goal=state.goal.text)
    ceiling = min(max_transitions or program.max_steps + 2, program.max_steps + 2)
    runtime = Runtime(
        limits=Limits(max_transitions=ceiling,
                      max_calls=10 ** 9, max_tokens=10 ** 9, wall_seconds=300.0),
        runner=CallbackRunner(run_one),
        after_commit=after_commit,
        emit=None,   # 兼容期：新增事件记在 runtime.events，不改变旧 sink 的事件序列
    )
    out = await runtime.interpret(LegacyProgram(program, scope), state)
    result = as_run_result(out, state)
    await _emit(scope, state, "run.end", status=str(result.status),
                steps=state.step_index)
    return result


def as_run_result(out: Outcome, state: State) -> RunResult:
    """新内核的字符串状态 → 既有 ``RunResult``（七态枚举）。"""
    try:
        status = RunStatus(out.status)
    except ValueError:
        status = RunStatus.FAILED
    state.status = status
    reason = str(out.extra.get("reason", ""))
    return RunResult(
        status=status,
        answer=out.answer,
        state=state,
        usage=dict(state.usage),
        error=(reason or None) if status is not RunStatus.COMPLETED else None,
        trace_id=state.trace_id,
        rev=state.rev,
    )


def _make_model_call(program: Any, scope: Any):
    """把 model_call 点上的层封成可调用对象交给 Actor（SPEC M2.2）。"""
    from harness.contracts.types import ModelRequest, ModelResponse

    layers = chain.resolve(program.layers, "model_call")

    async def call(request: ModelRequest) -> ModelResponse:
        async def terminal(req: ModelRequest) -> ModelResponse:
            reply = await scope.model.complete(list(req.messages), list(req.tools) or None)
            return ModelResponse(reply=reply)

        if layers:
            return await chain.execute(layers, request, terminal)
        return await terminal(request)

    return call


async def _emit(scope: Any, state: State, name: str, **fields: Any) -> None:
    """事件是唯一对外观察面；观测失败不得影响运行（SPEC M10.1）。"""
    sink = getattr(scope, "events", None)
    if sink is None:
        return
    try:
        await sink.emit(RunEvent(name=name, trace_id=state.trace_id, fields=fields))
    except Exception:  # noqa: BLE001
        pass


async def _identity(req):
    return StepResponse(step=getattr(req, "step", None))
