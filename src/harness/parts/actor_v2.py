"""LlmActor（插点 ④ 决策 + ⑥ 执行，SPEC M3.1）。

只做执行，不做评估；取景/编码/记账都在这里完成，不泄漏给策略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.contracts.types import ActionResult, Done, Step, ToolContext, usage_total


@dataclass
class LlmActor:
    model: Any
    tools: Any = None                     # ToolRegistry
    name: str = "actor"

    async def propose(self, state: Any, scope: Any) -> Step | Done:
        """决定下一步：取景 → 编码 → （经 model_call 链）问模型 → 解析 tool_call。

        取景永远在这里做；`scope.model_call` 由内核提供（内含护栏/缓存等层），
        所以本类不需要知道链的存在，也不需要 import kernel。
        """
        from harness.contracts.types import ModelReply, ModelRequest

        schemas = self.tools.schemas() if self.tools is not None else None
        frame = await scope.framer.frame(state, budget=scope.budget)
        pack = await scope.encoder.encode(frame)
        request = ModelRequest(
            state=state,
            messages=tuple(pack.messages),
            tools=tuple(schemas or ()),
            budget=scope.budget,
            frame=frame,
        )

        model_call = getattr(scope, "model_call", None)
        if model_call is not None:
            reply = (await model_call(request)).reply
        else:
            reply = await self.model.complete(pack.messages, schemas)

        usage = dict(getattr(reply, "usage", {}) or {})
        # 模型回包用量只交给 _commit 记账；这里不再自查、不再自行 spend，
        # 避免与 RunResult.usage / Budget 双计（M01/M03/M04）。
        state.data["_pending_usage"] = {"calls": 1, "tokens": usage_total(usage)}

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
