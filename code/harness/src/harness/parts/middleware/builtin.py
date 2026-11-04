"""四个内置层（SPEC M13.4）：Context / Checkpoint / BudgetGuard / Trace。

只实现与 step/model_call 链直接相关的四层；其余层在后续迭代补齐。
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from harness.contracts.events import RunEvent
from harness.contracts.types import Budget, ModelRequest, ModelResponse, StepRequest, StepResponse
from harness.parts.framing import ChatEncoder, ModelFramer
from harness.parts.middleware.base import Layer, layer


# ------------------------------------------------------------------ Context


def context_layer(*, system: str = "", encoder: Any = None) -> Layer:
    """插点 model_call：取景 → 编码，替换请求里的消息（SPEC M6）。"""
    framer = ModelFramer(system=system)
    enc = encoder or ChatEncoder()

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ModelRequest) or req.state is None:
                return await nxt(req)
            frame = await framer.frame(req.state, budget=req.budget or Budget())
            pack = await enc.encode(frame)
            return await nxt(replace(req, messages=tuple(pack.messages), frame=frame))

        return handler

    return layer("context", ["model_call"], build, before=["input_guard"])


# ------------------------------------------------------------------ Checkpoint


def checkpoint_layer(*, store: Any, cap: str = "store") -> Layer:
    """插点 step：每步落盘，rev 递增（不变量 1）。"""

    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            state = getattr(req, "state", None)
            if state is not None and isinstance(response, StepResponse):
                await store.put(
                    getattr(req, "ns", None) or state_namespace(state),
                    state.session.session_id,
                    state,
                    expect_rev=state.rev,
                )
            return response

        return handler

    return layer("checkpoint", ["step"], build, needs=[cap], after=["validate"])


def state_namespace(state: Any) -> Any:
    from harness.contracts.types import Namespace

    return Namespace(
        tenant=state.session.tenant or "default",
        user=state.goal.user_id or "anonymous",
        session=state.session.session_id,
    )


# ------------------------------------------------------------------ Budget


def budget_layer(*, budget: Budget) -> Layer:
    """插点 run + model_call：记账；超限抛 BudgetError（SPEC M8.2）。"""

    def build(nxt):
        async def handler(req):
            from harness.contracts.errors import BudgetExceeded

            if budget.exhausted:
                raise BudgetExceeded(f"预算耗尽：{budget.snapshot()}")
            response = await nxt(req)
            if isinstance(response, ModelResponse):
                used = int(response.usage.get("total", 0))
                budget.spend(tokens=used, calls=1)
            return response

        return handler

    return layer("budget", ["run", "model_call"], build, after=["tenancy"])


# ------------------------------------------------------------------ Trace


def trace_layer(*, sink: Any, clock: Any = None) -> Layer:
    """全部插点：开/闭 span 并发事件（SPEC M10.1）。异常不得影响请求。"""

    def build(nxt):
        async def handler(req):
            name = type(req).__name__
            start = int((clock.now().timestamp() if clock else time.time()) * 1000)
            try:
                response = await nxt(req)
            finally:
                end = int((clock.now().timestamp() if clock else time.time()) * 1000)
                try:
                    await sink.emit(
                        RunEvent(
                            name="span.end",
                            ts_ms=end,
                            fields={"request": name, "start_ms": start, "end_ms": end},
                        )
                    )
                except Exception:  # noqa: BLE001 - 观测不得影响请求
                    pass
            return response

        return handler

    return layer("trace", ["run", "step", "model_call", "tool_call"], build,
                 needs=["events"], before=["audit"])


__all__ = ["context_layer", "checkpoint_layer", "budget_layer", "trace_layer", "state_namespace"]
