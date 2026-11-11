"""Actor：一次决策 + 一次执行（单版本，BL-1 合并完成）。

职责边界（SPEC M3.1）：
  * 决策（``propose``）：取景 → 编码 → 经 model_call 链问模型 → 解析 tool_call；
    不评估、不决定下一步。
  * 执行（``step``）：调用一次工具，失败回灌模型由下一轮修正。

``resilience`` 与 ``model_call`` 插点都是可选能力：装配期注入后，模型 / 工具调用走插点链与
限流 / 重试 / 熔断，Actor 本身不需要知道链的存在。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.contracts.state import State
from harness.contracts.types import (
    ActionResult,
    Done,
    Pack,
    Step,
    ToolContext,
    usage_total,
)


@dataclass
class LlmActor:
    """执行终端（``propose`` / ``step``）：以取景 + 编码完成决策，吸收 resilience / model_call 插点。"""

    model: Any
    tools: Any = None                     # ToolRegistry
    name: str = "actor"
    resilience: Any = None
    model_call: Any = None

    async def propose(self, state: Any, scope: Any) -> Step | Done:
        """决定下一步：取景 → 编码 → （经 model_call 链）问模型 → 解析 tool_call。

        取景永远在这里做；``scope.model_call`` / 本实例的 ``model_call`` 由内核提供
        （内含护栏 / 缓存等层），所以本类不需要知道链的存在，也不需要 import kernel。
        """
        from harness.contracts.types import ModelRequest

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

        async def _ask() -> Any:
            mc = self.model_call or getattr(scope, "model_call", None)
            if mc is not None:
                return (await mc(request)).reply
            return await self.model.complete(pack.messages, schemas)

        reply = await (self.resilience.call(_ask) if self.resilience is not None else _ask())

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

            async def _invoke() -> Any:
                return await tool.invoke(step.args, ctx)

            output = await (
                self.resilience.call(_invoke) if self.resilience is not None else _invoke()
            )
        except Exception as exc:            # noqa: BLE001 - 工具失败回灌
            return ActionResult(
                step_id=step.id, ok=False, error=str(exc), tool_name=step.tool_name
            )
        return ActionResult(step_id=step.id, ok=True, output=output, tool_name=step.tool_name)


__all__ = ["LlmActor"]
