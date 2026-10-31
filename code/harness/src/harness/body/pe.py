"""Plan-and-Execute：先产出一份可审查的 Plan，再逐步执行。"""

from __future__ import annotations

from dataclasses import asdict

from ..contracts import Done, Plan, Step


class PlanExecutePolicy:
    def __init__(self, planner, max_steps: int = 20) -> None:
        self.planner = planner
        self.max_steps = max_steps

    async def next_step(self, state, ctx) -> Step | Done:
        section = state.section("pe")
        if "plan" not in section:
            plan = await self.planner.plan(state.goal, state)
            if not isinstance(plan, Plan):
                raise TypeError("Planner.plan 必须返回 Plan")
            section["plan"] = asdict(plan)
            section["index"] = 0

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
