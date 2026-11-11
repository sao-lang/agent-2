"""Planner：只属于 Plan-and-Execute（原 ``parts/body/planner.py``，BL-1 合并）。"""

from __future__ import annotations

from dataclasses import dataclass

from harness.contracts.state import State
from harness.contracts.types import Goal, Plan


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


__all__ = ["FunctionPlanner", "ScriptedPlanner"]
