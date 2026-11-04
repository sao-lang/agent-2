"""Delivery：出口。终止态、引用、脱敏都在这里收口。"""

from __future__ import annotations

from harness.contracts.types import ApprovalRequest, RunStatus
from harness.contracts.result import RunResult
from harness.contracts.state import State


class DefaultDelivery:
    async def finish(self, state: State, status: RunStatus, *,
                     answer: str = "", error: str | None = None,
                     pending: ApprovalRequest | None = None) -> RunResult:
        citations = list(state.data.get("citations", []))
        return RunResult(
            status=status,
            answer=answer,
            state=state,
            usage=dict(state.usage),
            citations=citations,
            pending=pending,
            error=error,
            trace_id=state.trace_id,
            metadata={"budget": state.data.get("budget", {})},
        )
