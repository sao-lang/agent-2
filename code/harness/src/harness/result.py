"""RunResult：一次运行的最终结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import ApprovalRequest, RunStatus
from .state import State


@dataclass
class RunResult:
    status: RunStatus
    answer: str = ""
    state: State | None = None
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    citations: list[str] = field(default_factory=list)
    pending: ApprovalRequest | None = None
    error: str | None = None
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.DEGRADED)
