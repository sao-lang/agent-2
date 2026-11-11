"""治理协议：决策、路由、校验、观测、出口（SPEC M3–M10）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.events import RunEvent
    from harness.contracts.state import State
    from harness.contracts.types import (
        ActionResult,
        ApprovalRequest,
        Goal,
        Plan,
        Route,
        RunResult,
        Verdict,
    )


@runtime_checkable
class Actor(Protocol):
    """插点 ④ 决策 + ⑥ 执行。只做执行，不做评估（SPEC M3.1）。"""

    async def propose(self, state: "State", scope: Any) -> Any: ...

    async def step(self, step: Any, state: "State", scope: Any) -> "ActionResult": ...


@runtime_checkable
class Router(Protocol):
    """分派层：不解决问题，只决定谁来解决（SPEC M4.1）。"""

    async def route(self, goal: "Goal", state: "State | None" = None) -> "Route": ...


@runtime_checkable
class Reflector(Protocol):
    """单步结果质量判定（SPEC M5.1）。"""

    async def review(self, result: "ActionResult", state: "State") -> "Verdict": ...


@runtime_checkable
class Validator(Protocol):
    """最终答案判定。"""

    async def validate(self, answer: str, state: "State") -> "Verdict": ...


@runtime_checkable
class Tracer(Protocol):
    """带 span 语义的事件出口；异常不得影响请求（SPEC M10.1）。"""

    async def emit(self, event: "RunEvent") -> None: ...


@runtime_checkable
class Delivery(Protocol):
    """出口唯一：只有它能产出 `RunResult`（SPEC M10.3）。"""

    async def finish(
        self,
        state: "State",
        status: Any,
        *,
        answer: str = "",
        reason: str = "",
        pending: "ApprovalRequest | None" = None,
    ) -> "RunResult": ...


__all__ = ["Actor", "Router", "Reflector", "Validator", "Tracer", "Delivery"]
