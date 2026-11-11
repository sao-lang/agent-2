"""策略（SPEC M3.3）：签名 `next_step(state, scope)`。

单版本收敛（AUDIT BL-1）：与 ``RunScope`` 配套的唯一策略实现。
``PlanExecutePolicy`` 把计划的 section 记账、``replan_all`` 重规划与
``budget.replans`` 镜像计数全部收在这里。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
    """先计划再执行；`Planner` 只属于这里。

    全部进度记在 ``state.section("pe")``（plan/index/replans），策略实例
    本身无状态——崩溃恢复与重放天然成立。``Verdict.replan_all`` 触发回到
    Planner 重出计划（带上已完成步骤与失败原因），次数受 ``max_replans``
    上限约束（超限降级），并镜像到 ``budget.replans``；
    ``reflector=None``（含 NullReflector 场景）时该路径完全不存在。
    """

    planner: Any
    name: str = "pe"
    max_steps: int = 20
    max_replans: int = 2
    reflector: Any = None              # Reflector 协议；None = 无重规划路径
    budget: Any = None                 # 可选：replans 镜像计数

    async def next_step(self, state: Any, scope: Any) -> Step | Done:
        section = state.section("pe")
        if "plan" not in section:
            plan = await self.planner.plan(state.goal, state)
            if not isinstance(plan, Plan):
                raise TypeError("Planner.plan 必须返回 Plan")
            section["plan"] = asdict(plan)
            section["index"] = 0
            section["replans"] = 0

        # ---- A1：重规划检查（只查上一轮的结果；首步之前无结果可查）----
        if self.reflector is not None and section.get("index", 0) > 0:
            last_result = state.data.get("last_result")
            if last_result is not None:
                verdict = await self.reflector.review(last_result, state)
                if getattr(verdict, "action", "accept") == "replan_all":
                    return await self._replan(state, section,
                                              reason=str(getattr(verdict, "reason", "")))

        raw = section["plan"]
        plan = Plan(
            id=raw["id"],
            steps=[Step(**item) for item in raw["steps"]],
            rev=int(raw.get("rev", 0)),
        )
        index = int(section.get("index", 0))
        if index >= len(plan.steps) or index >= self.max_steps:
            return Done(answer=state.data.get("last_output", ""), reason="plan_done")

        step = plan.steps[index]
        section["index"] = index + 1
        return step

    async def _replan(self, state: Any, section: dict, *, reason: str) -> Step | Done:
        """回到 Planner 重出计划；次数受上限约束，超限降级交付。"""
        replans = int(section.get("replans", 0))
        if replans >= self.max_replans:
            return Done(answer=state.data.get("last_output", ""),
                        reason=f"replan_limit({replans})")

        completed = self._completed_steps(section)
        # 重规划上下文写进自己的命名空间：Planner 可读，其余组件不感知
        section["replan_context"] = {
            "reason": reason,
            "completed": completed,
            "last_error": state.last_error or "",
        }

        plan = await self.planner.plan(state.goal, state)
        if not isinstance(plan, Plan):
            raise TypeError("Planner.plan 必须返回 Plan")
        replans += 1
        new_plan = Plan(id=plan.id, steps=plan.steps, rev=plan.rev + replans)
        section["plan"] = asdict(new_plan)
        section["index"] = 0
        section["replans"] = replans
        if self.budget is not None and hasattr(self.budget, "replans"):
            self.budget.replans = max(self.budget.replans, replans)   # 镜像，不回滚
        return await self.next_step(state, None)   # 立即取新计划的第一个步骤

    @staticmethod
    def _completed_steps(section: dict) -> list[dict]:
        """已完成步骤 = 计划中 index 之前的部分（给 Planner 的原始依据）。"""
        raw = section.get("plan") or {}
        index = int(section.get("index", 0))
        return list(raw.get("steps", []))[:index]


__all__ = ["ReactPolicy", "WorkflowPolicy", "PlanExecutePolicy"]
