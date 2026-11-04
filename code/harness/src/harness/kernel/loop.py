"""L0 内核：唯一循环（SPEC M2.1）。

只做四件事：取步、过四段、记账、存档；其余全在部件里。
"""

from __future__ import annotations

from typing import Any

from harness.contracts.errors import HarnessError
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.status import RunStatus
from harness.contracts.types import Done, Effect, Step, StepRequest, StepResponse, ToolRequest, ToolResponse
from harness.kernel import chain, stage


async def run_loop(*, program: Any, state: State, scope: Any, record_effects: list | None = None) -> RunResult:
    """跑一次完整运行。

    `record_effects` 非空时进入干跑模式：工具调用只记账、不执行。
    """
    tool_layers = chain.resolve(program.layers, "tool_call")
    step_layers = chain.resolve(program.layers, "step")

    async def terminal(step: Step, st: State):
        if record_effects is not None:
            record_effects.append(Effect(kind="tool", step=step))
            from harness.contracts.types import ActionResult

            return ActionResult(step_id=step.id, ok=True, output="[dry-run]")
        return await scope.actor.step(step, st, scope)

    while state.step_index < program.max_steps:
        if scope.budget is not None and scope.budget.exhausted:
            return _finish(state, RunStatus.DEGRADED, reason="budget")

        try:
            decision = await program.body.next_step(state, scope)
        except Exception as exc:  # noqa: BLE001 - 决策失败也要归类
            failure = await scope.filter.classify(exc, phase="step", state=state) \
                if scope.filter is not None else None
            return _failure(state, failure, exc)

        if isinstance(decision, Done):
            state.status = RunStatus.COMPLETED
            return _finish(state, RunStatus.COMPLETED, answer=decision.answer)

        if not isinstance(decision, Step):
            raise HarnessError(f"BodyPolicy 返回非法类型：{type(decision)!r}")

        result = await stage.run_stages(
            decision,
            state,
            terminal=terminal,
            gate=scope.guard,
            checks=tuple(scope.pipes),
            layers=tool_layers,
            classify=scope.filter,
        )
        if result.failure is not None:
            return _finish(state, result.failure.status, reason=result.failure.reason)

        if result.result is not None:
            state.data["last_output"] = result.result.output
            state.data["last_result"] = result.result

        state.step_index += 1

        # step 点：checkpoint / validate / taskboard 等
        if step_layers:
            await chain.execute(
                step_layers, StepRequest(state=state, step=decision), _identity
            )

    return _finish(state, RunStatus.DEGRADED, reason="max_steps")


async def _identity(req):
    return StepResponse(step=getattr(req, "step", None))


def _finish(state: State, status: RunStatus, *, answer: str = "", reason: str = "") -> RunResult:
    state.status = status
    return RunResult(
        status=status,
        answer=answer,
        state=state,
        usage=dict(state.usage),
        error=(reason or None) if status not in (RunStatus.COMPLETED,) else None,
        trace_id=state.trace_id,
        rev=state.rev,
    )


def _failure(state: State, failure: Any, exc: BaseException) -> RunResult:
    if failure is None:
        state.last_error = str(exc)
        return _finish(state, RunStatus.FAILED, reason=str(exc))
    state.last_error = failure.reason
    return _finish(state, failure.status, reason=failure.reason)


__all__ = ["run_loop"]
