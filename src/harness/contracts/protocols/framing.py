"""数据视图：取景与编码（SPEC M6）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.state import State
    from harness.contracts.types import Budget, Frame, Pack


@runtime_checkable
class Framer(Protocol):
    """取景：选哪些、怎么排、超预算丢谁。不拼字符串、不决定格式。"""

    kind: str

    async def frame(self, state: "State", *, budget: "Budget") -> "Frame": ...


@runtime_checkable
class Encoder(Protocol):
    """编码：Frame → 载荷。不决定留哪条。"""

    fmt: str

    async def encode(self, frame: "Frame") -> Any: ...


@runtime_checkable
class Context(Protocol):
    """既有形状，保留兼容；新代码用 Framer + Encoder。"""

    async def assemble(self, state: "State", budget_tokens: int) -> "Pack": ...


__all__ = ["Framer", "Encoder", "Context"]
