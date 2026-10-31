"""Workflow：步骤由开发者写死；模型不决定顺序。"""

from __future__ import annotations

from dataclasses import replace

from ..contracts import Done, Step


class WorkflowPolicy:
    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)

    async def next_step(self, state, ctx) -> Step | Done:
        index = int(state.data.get("workflow_index", 0))
        if index >= len(self.steps):
            return Done(answer=state.data.get("last_output", ""))
        step = replace(self.steps[index], id=self.steps[index].id or f"w{index + 1}")
        state.data["workflow_index"] = index + 1
        return step
