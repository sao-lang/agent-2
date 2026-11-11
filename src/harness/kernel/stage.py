"""L0 内核：四段执行链（Gate → Check → Wrap → Classify）。

四段的失败语义不同，所以不能合并成一条洋葱（SPEC M2.2）：

    Gate     动作准入，返回判定，不抛异常，可短路
    Check    参数校验与转换，抛 ValidationError
    Wrap     包裹执行，异常原样穿透
    Classify 异常 → Failure 的唯一映射点，不吞异常

P1 只提供编排与语义；具体实现（Guard/Pipe/Filter 的内置件）在 P4 接入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.types import (
    ActionResult,
    Failure,
    GuardDecision,
    RunStatus,
    Step,
)

Terminal = Callable[[Step, State], Awaitable[ActionResult]]
Layer = Callable[..., Awaitable[ActionResult]]


@dataclass(frozen=True)
class StageRequest:
    """Wrap 段的请求形状（SPEC M1.7）。层拿它构造新 Response，不原地改。

    P1 合并 §4.3.2：原名 ``ToolRequest`` 与契约层的 ``ToolRequest``
    （step + spec，middleware 消费）同名不同形状，改名消除歧义。
    """

    step: Step
    state: State


@dataclass(frozen=True)
class StageResult:
    """一段链走完的结局：要么有动作结果，要么有失败分类。"""

    step: Step
    result: ActionResult | None = None
    failure: Failure | None = None

    @property
    def ok(self) -> bool:
        return self.result is not None and self.failure is None


class AllowAllGate:
    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.allow()


class DenyAllGate:
    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.deny("DenyAllGate")


class IdentityCheck:
    async def transform(self, step: Step, state: State) -> Step:
        return step


class DefaultClassify:
    """异常 → Failure 的默认映射（SPEC M16.1.1）；未知异常 fail-closed。"""

    async def classify(self, exc: BaseException, *, phase: str, state: State) -> Failure:
        import asyncio

        from harness.contracts.approval_errors import ApprovalRequired
        from harness.contracts.errors import (
            ApprovalExpired,
            BudgetExceeded,
            ConfigError,
            ConcurrencyError,
            ContractError,
            GuardDenied,
            PolicyError,
            ToolError,
            TransientError,
            ValidationError,
        )

        if isinstance(exc, asyncio.CancelledError):
            return Failure(RunStatus.CANCELLED, "cancelled", False)
        if isinstance(exc, ApprovalRequired):
            return Failure(RunStatus.NEEDS_APPROVAL, exc.reason or "approval_required", False)
        if isinstance(exc, (GuardDenied, PolicyError)):
            return Failure(RunStatus.REFUSED, f"policy:{exc}", False)
        if isinstance(exc, ApprovalExpired):
            return Failure(RunStatus.REFUSED, "approval:expired", False)
        if isinstance(exc, ConcurrencyError):
            return Failure(RunStatus.REFUSED, "concurrency_conflict", False)
        if isinstance(exc, ValidationError):
            return Failure(RunStatus.REFUSED, f"invalid_args:{exc.field}", False)
        if isinstance(exc, TransientError):
            return Failure(RunStatus.DEGRADED, "transient_exhausted", True)
        if isinstance(exc, BudgetExceeded):
            return Failure(RunStatus.DEGRADED, "budget", False)
        if isinstance(exc, ToolError):
            return Failure(RunStatus.DEGRADED, "tool", True)
        if isinstance(exc, (ConfigError, ContractError)):
            return Failure(RunStatus.FAILED, type(exc).__name__, False)
        return Failure(RunStatus.FAILED, type(exc).__name__, False)


async def run_stages(
    step: Step,
    state: State,
    *,
    terminal: Terminal,
    gate: Any = None,
    checks: Sequence[Any] = (),
    layers: Sequence[Layer] = (),
    classify: Any = None,
) -> StageResult:
    """按固定顺序走四段；**顺序不可调、不可合并、不可省略**。"""
    gate = gate or AllowAllGate()
    classify = classify or DefaultClassify()

    # ① Gate：返回判定，不抛异常
    decision: GuardDecision = await gate.check(step, state)
    if decision.action == "deny":
        return StageResult(step, failure=Failure(RunStatus.REFUSED, f"policy:{decision.reason}", False))
    if decision.action == "ask":
        return StageResult(step, failure=Failure(RunStatus.NEEDS_APPROVAL, decision.reason, False))

    # ② Check：校验与转换
    try:
        for check in checks:
            step = await check.transform(step, state)
    except Exception as exc:  # noqa: BLE001 - 统一走 Classify
        return StageResult(step, failure=await classify.classify(exc, phase="check", state=state))

    # ③ Wrap：洋葱包住终端（层签名是 (ToolRequest, nxt) -> ActionResult）
    async def base(req: StageRequest) -> ActionResult:
        return await terminal(req.step, req.state)

    handler: Callable[[StageRequest], Awaitable[ActionResult]] = base
    for layer in reversed(list(layers)):
        inner, lay = handler, layer

        async def handler(
            req: StageRequest, *, _inner=inner, _lay=lay
        ) -> ActionResult:  # noqa: ANN001
            return await _lay(req, _inner)

    # ④ Classify：异常 → Failure 的唯一映射点
    try:
        result = await handler(StageRequest(step=step, state=state))
    except Exception as exc:  # noqa: BLE001 - 运行边界
        return StageResult(step, failure=await classify.classify(exc, phase="wrap", state=state))
    return StageResult(step, result=result)


# ------------------------------------------------------------------ 效应四段链


async def run_effect_stages(
    effect: Any,
    state: State,
    *,
    terminal: Any,
    layers: Sequence[Any] = (),
    guard: Any = None,
    checks: Sequence[Any] = (),
    classify: Any = None,
    to_step: Any,
) -> tuple[dict[str, Any], bool]:
    """效应侧四段链（G06：与 ``run_stages`` 同源同序，effects.py 不再内联重写）。

    返回 ``(result_dict, cacheable)``：Gate/Check 短路的结果**不进幂等缓存**
    （重判比回放拒绝更正确），只有 Wrap 段真正执行过的结果可回放。
    ``to_step`` 由调用方注入（``kernel.effects.to_step``），避免契约层反向依赖。
    """
    from harness.contracts.types import GuardDecision

    def _refused(reason: str) -> dict[str, Any]:
        return {"ok": False, "error": reason, "status": "refused"}

    step = to_step(effect)

    # ① Gate：EffectLayer.gate（allow/deny/ask）+ 可注入 Guard（allow/deny/ask）
    for layer in layers:
        verdict = await _maybe_await(layer.gate(effect, state))
        if verdict in ("deny", "ask"):
            return ({"ok": False,
                     "error": f"{'gate' if verdict == 'deny' else 'approval'}:{layer.name}",
                     "status": "refused" if verdict == "deny" else "needs_approval"},
                    False)
    if guard is not None:
        verdict: GuardDecision = await _maybe_await(guard.check(step, state))
        if getattr(verdict, "action", "allow") in ("deny", "ask"):
            return ({"ok": False,
                     "error": f"policy:{getattr(verdict, 'reason', '')}",
                     "status": "refused" if verdict.action == "deny" else "needs_approval"},
                    False)

    # ② Check：EffectLayer.check 抛异常即参数非法；Pipe 做 Step 转换
    try:
        for layer in layers:
            await _maybe_await(layer.check(effect, state))
        for pipe in checks:
            step = await _maybe_await(pipe.transform(step, state))
    except Exception as exc:  # noqa: BLE001 - 统一走 Classify
        return (await _classify_failure(exc, state, phase="check", classify=classify),
                False)

    # ③ Wrap：洋葱，外层在最外；终端是 (effect, state) -> result dict
    handler: Callable = terminal
    for layer in reversed(list(layers)):
        handler = layer.wrap(effect, handler) or handler

    # ④ Classify：异常 → 失败归类的唯一映射点
    try:
        result = _as_dict(await _maybe_await(handler(effect, state)))
    except Exception as exc:  # noqa: BLE001 - 运行边界
        return (await _classify_failure(exc, state, phase="wrap", classify=classify),
                False)
    return (result, True)


async def _maybe_await(value: Any) -> Any:
    import inspect

    return await value if inspect.isawaitable(value) else value


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {
        "ok": bool(getattr(value, "ok", True)),
        "output": getattr(value, "output", ""),
        "error": getattr(value, "error", "") or "",
        "tokens": int(getattr(value, "tokens", 0) or 0),
        "raw": value,
    }


async def _classify_failure(exc: BaseException, state: State, *, phase: str,
                            classify: Any) -> dict[str, Any]:
    classifier = classify or DefaultClassify()
    try:
        failure = await classifier.classify(exc, phase=phase, state=state)
        status = str(getattr(failure, "status", "failed"))
        reason = getattr(failure, "reason", str(exc))
    except Exception:  # noqa: BLE001 - 归类器本身坏了也不能吞掉结果
        status, reason = "failed", str(exc)
    return {"ok": False, "error": f"{type(exc).__name__}:{exc}",
            "status": status, "reason": reason}
