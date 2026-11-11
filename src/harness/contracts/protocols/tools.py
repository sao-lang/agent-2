"""工具与执行原语（SPEC M3.5）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.types import ToolContext, ToolResult, ToolSpec


@runtime_checkable
class Tool(Protocol):
    """唯一有副作用的执行原语。

    推荐形状：`spec` 携带元数据，`invoke` 接收能力注入的 `ToolContext`。
    既有 `name/schema/invoke(args)` 形状由 `FunctionTool` 兼容提供。
    """

    spec: "ToolSpec"

    async def invoke(self, args: dict[str, Any], ctx: "ToolContext") -> "ToolResult": ...


__all__ = ["Tool"]
