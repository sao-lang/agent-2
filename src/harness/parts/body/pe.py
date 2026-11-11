"""Plan-and-Execute：先产出一份可审查的 Plan，再逐步执行。

v3.1（SUPPLEMENT A1）：接上 ``Verdict.replan_all``——Reflector 判定当前计划
整体不可救时，回到 Planner 重出计划（带上已完成步骤与失败原因），而不是
逐条 retry。重规划次数计入 ``state.section("pe")["replans"]``，并在注入
Budget 时镜像到 ``budget.replans``，受 ``max_replans`` 上限约束（超限降级）。

替换实验：注入返回 ``replan_all`` 的 Reflector → 计划被重出且计数递增；
``reflector=None``（含 NullReflector 场景）时该路径完全不存在。
"""

from __future__ import annotations

from dataclasses import asdict

from harness.contracts.types import Done, Plan, Step


class PlanExecutePolicy:
    def __init__(self, planner, max_steps: int = 20, *,
                 reflector=None, max_replans: int = 2, budget=None) -> None:
        self.planner = planner
        self.max_steps = max_steps
        self.reflector = reflector          # Reflector 协议；None = 无重规划路径
        self.max_replans = max_replans
        self.budget = budget                # 可选：replans 镜像计数

    async def next_step(self, state, ctx) -> Step | Done:
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

    async def _replan(self, state, section, *, reason: str) -> Step | Done:
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
    def _completed_steps(section) -> list[dict]:
        """已完成步骤 = 计划中 index 之前的部分（给 Planner 的原始依据）。"""
        raw = section.get("plan") or {}
        index = int(section.get("index", 0))
        return list(raw.get("steps", []))[:index]


__all__ = ["PlanExecutePolicy"]
