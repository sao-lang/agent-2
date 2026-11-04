"""LlmActor（插点 ④ 决策 + ⑥ 执行，SPEC M3.1）。

只做执行，不做评估；取景/编码/记账都在这里完成，不泄漏给策略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.contracts.types import ActionResult, Done, Step, ToolContext


@dataclass
class LlmActor:
    model: Any
    tools: Any = None                     # ToolRegistry
    name: str = "actor"

    async def propose(self, state: Any, scope: Any) -> Step | Done:
        """决定下一步：取景 → 编码 → 问模型 → 解析 tool_call。"""
        frame = await scope.framer.frame(state, budget=scope.budget)
        pack = await scope.encoder.encode(frame)
        reply = await self.model.complete(
            pack.messages, self.tools.schemas() if self.tools is not None else None
        )

        usage = dict(getattr(reply, "usage", {}) or {})
        tokens = int(usage.get("total", usage.get("tokens", 0)) or 0)
        state.add_usage(tokens=tokens, calls=1)
        if scope.budget is not None:
            scope.budget.spend(tokens=tokens, calls=1)

        calls = list(getattr(reply, "tool_calls", []) or [])
        if not calls:
            return Done(answer=str(getattr(reply, "content", "")))
        call = calls[0]                    # 一轮只取第一个：并行工具不支持（ADR 12）
        return Step(
            id=f"s{state.step_index + 1}",
            instruction=str(getattr(reply, "content", "") or ""),
            tool_name=call.name,
            args=dict(call.args),
            index=state.step_index,
        )

    async def step(self, step: Step, state: Any, scope: Any) -> ActionResult:
        """执行一次工具调用。失败回灌模型，由下一轮修正。"""
        if not step.tool_name:
            return ActionResult(step_id=step.id, ok=True, output=step.instruction)
        try:
            tool = self.tools.get(step.tool_name)
            ctx = ToolContext(
                fs=scope.fs,
                sandbox=scope.sandbox,
                artifacts=scope.artifacts,
                secrets=scope.secrets,
                state=state,
                signal=getattr(scope, "signal", None),
            )
            output = await tool.invoke(step.args, ctx)
        except Exception as exc:            # noqa: BLE001 - 工具失败回灌
            return ActionResult(step_id=step.id, ok=False, error=str(exc),
                                tool_name=step.tool_name)
        return ActionResult(step_id=step.id, ok=True, output=output, tool_name=step.tool_name)


__all__ = ["LlmActor"]
