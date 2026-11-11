"""审批与幂等相关的错误类型（P4 增补）。"""

from __future__ import annotations

from harness.contracts.errors import HarnessError


class ApprovalRequired(HarnessError):
    """准入层判定"需要人点头"：由 `Classify` 映射为 NEEDS_APPROVAL。

    携带的信息足够重建一张审批卡片，且**不含**任何执行结果——此刻还没有结果。
    """

    def __init__(
        self,
        step_id: str,
        *,
        reason: str = "",
        card: dict | None = None,
        tool: str = "",
    ) -> None:
        super().__init__(f"需要审批：{tool or step_id} ({reason})")
        self.step_id = step_id
        self.reason = reason
        self.card = card or {}
        self.tool = tool


__all__ = ["ApprovalRequired"]
