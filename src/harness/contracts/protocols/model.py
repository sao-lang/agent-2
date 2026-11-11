"""模型后端（SPEC M12.1）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.types import ModelDelta, ModelReply, ResponseFormat


@runtime_checkable
class Model(Protocol):
    """一次补全 + 一次流式补全。usage 必须归一化成 {input, output, total}。"""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        response_format: "ResponseFormat | None" = None,
    ) -> "ModelReply": ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator["ModelDelta"]: ...


__all__ = ["Model"]
