"""事件类型（SPEC M1.4、M10.1）。零依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 事件名（SPEC M10.1 的观测面 + v3 解释器插点，PROPOSAL §6）
EVENT_NAMES = (
    "run.start",
    "run.end",
    "step.start",
    "step.end",
    "model.start",
    "model.delta",
    "model.end",
    "tool.start",
    "tool.end",
    "guardrail",
    "approval.required",
    "approval.resolved",
    "checkpoint",
    "error",
    "hook.error",
    "guardrail_error",
    # v3：解释器与效应系统的新插点
    "transition",
    "effect",
    "commit",
    "node",
)


@dataclass(frozen=True)
class TraceEvent:
    """v1 形状，保留兼容。"""

    trace_id: str
    span_id: str
    name: str
    kind: str = "span"
    parent_id: str | None = None
    start_ms: int = 0
    end_ms: int = 0
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunEvent:
    """v2 统一事件（唯一对外观察面）。"""

    name: str
    trace_id: str = ""
    span_id: str = ""
    parent_id: str | None = None
    kind: str = "span"
    ts_ms: int = 0
    fields: dict[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass(frozen=True)
class HookEvent:
    """hook 的载荷：只读，返回值被忽略（SPEC M13.6）。"""

    point: str
    state_id: str = ""
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """一次插点的起止。`parent_id` 必须真实填写（SPEC M11.4）。"""

    trace_id: str
    span_id: str
    name: str
    parent_id: str | None = None
    start_ms: int = 0
    end_ms: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    def end(self, **fields: Any) -> None:
        self.fields.update(fields)


__all__ = ["EVENT_NAMES", "TraceEvent", "RunEvent", "HookEvent", "Span"]
