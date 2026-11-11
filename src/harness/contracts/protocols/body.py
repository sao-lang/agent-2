"""主体层：决策与计划（SPEC M3）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.state import State
    from harness.contracts.types import Done, Goal, Plan, Step


@runtime_checkable
class BodyPolicy(Protocol):
    """唯一策略缝：内核只问"下一步是什么"，不问"怎么想出来的"。"""

    name: str

    async def next_step(self, state: "State", scope: Any) -> "Step | Done": ...


@runtime_checkable
class Planner(Protocol):
    """只在 Plan-and-Execute 里出现（ReAct / Workflow 不持有 Planner）。"""

    async def plan(self, goal: "Goal", state: "State") -> "Plan": ...


__all__ = ["BodyPolicy", "Planner"]
