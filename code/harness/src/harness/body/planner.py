"""Planner：只属于 Plan-and-Execute。"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import Goal, Plan, Step
from ..state import State


@dataclass
class ScriptedPlanner:
    """固定计划；示例与测试用。"""

    plan_obj: Plan

    async def plan(self, goal: Goal, state: State) -> Plan:
        return self.plan_obj


class FunctionPlanner:
    def __init__(self, fn) -> None:
        self.fn = fn

    async def plan(self, goal: Goal, state: State) -> Plan:
        value = self.fn(goal, state)
        if hasattr(value, "__await__"):
            value = await value
        return value
