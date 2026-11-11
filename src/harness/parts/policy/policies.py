"""策略（SPEC M3.3）：v2 签名 `next_step(state, scope)`。

v1 的 `parts/body/*` 保留兼容；这里是与 `RunScope` 配套的实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from harness.contracts.types import Done, Plan, Step


@dataclass
class ReactPolicy:
    """每轮由 `Actor.propose` 决定下一步；没有显式计划。"""

    name: str = "react"
    max_tool_calls: int = 1

    async def next_step(self, state: Any, scope: Any) -> Step | Done:
        return await scope.actor.propose(state, scope)


@dataclass
class WorkflowPolicy:
    """固定步骤：能提前写死就不要用循环。"""

    steps: Sequence[Step]
    name: str = "workflow"
    on_tool_error: str = "stop"
    _index: int = 0

    async def next_step(self, state: Any, scope: Any) -> Step | Done:
        if self._index >= len(self.steps):
            return Done(answer=str(state.data.get("last_output", "") or ""), reason="workflow_done")
        step = self.steps[self._index]
        self._index += 1
        return step


@dataclass
class PlanExecutePolicy:
    """先计划再执行；`Planner` 只属于这里。"""

    planner: Any
    name: str = "pe"
    max_replan: int = 2
    _plan: Plan | None = None
    _cursor: int = 0
    _replans: int = 0

    async def next_step(self, state: Any, scope: Any) -> Step | Done:
        if self._plan is None:
            self._plan = await self.planner.plan(state.goal, state)
            state.plan = self._plan
            self._cursor = 0
        if self._cursor >= len(self._plan.steps):
            return Done(answer=str(state.data.get("last_output", "") or ""), reason="plan_done")
        step = self._plan.steps[self._cursor]
        self._cursor += 1
        return step

    def replan(self) -> None:
        """`Verdict.action == "replan_all"` 时调用。"""
        if self._replans < self.max_replan:
            self._replans += 1
            self._plan = None
            self._cursor = 0


__all__ = ["ReactPolicy", "WorkflowPolicy", "PlanExecutePolicy"]
