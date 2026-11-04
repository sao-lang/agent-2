"""准入与护栏（SPEC M8.1、M9.2）。

两套判定必须分开：`Guard` 管「动作能不能做」，`Guardrail` 管「内容能不能进出」。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.state import State
    from harness.contracts.types import (
        Content,
        GuardDecision,
        GuardrailVerdict,
        Step,
        StreamState,
    )


@runtime_checkable
class Guard(Protocol):
    """段 Gate。返回判定、**不抛异常**、可短路。"""

    async def check_identity(self, goal: Any, ns: Any) -> "GuardDecision": ...

    async def check(self, step: "Step", state: "State") -> "GuardDecision": ...


@runtime_checkable
class Guardrail(Protocol):
    """五道闸的内容检测；检测与动作分离（SPEC M9.2）。"""

    name: str
    gates: frozenset[str]

    async def check(self, content: "Content", scope: Any) -> "GuardrailVerdict": ...


@runtime_checkable
class GuardrailStream(Guardrail, Protocol):
    """流式增量检测（SPEC M9.4）：窗口缓冲 + 结尾 flush。"""

    async def feed(self, delta: str, st: "StreamState") -> "GuardrailVerdict": ...

    async def flush(self, st: "StreamState") -> "GuardrailVerdict": ...


__all__ = ["Guard", "Guardrail", "GuardrailStream"]
