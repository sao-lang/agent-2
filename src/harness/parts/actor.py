"""Actor：一次决策 + 一次执行。

它不评估结果，也不决定下一步；这两件事分别归 Reflector 与 BodyPolicy。
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.contracts.types import ActionResult, Model, ModelReply, Pack, Step, ToolCall
from harness.contracts.errors import ToolError
from harness.contracts.state import State
from harness.parts.tools import ToolRegistry


@dataclass
class Actor:
    model: Model
    tools: ToolRegistry
    resilience: object | None = None
    #: G07：model_call 插点（callable(ModelRequest) -> ModelResponse）。
    #: None = 直调模型（兼容默认）；装配层注入后模型调用走插点链。
    model_call: Any = None

    async def decide(self, state: State, pack: Pack) -> ModelReply:
        from harness.contracts.types import ModelRequest

        if self.model_call is not None:
            request = ModelRequest(
                state=state, messages=tuple(pack.messages),
                tools=tuple(self.tools.schemas() or ()),
            )
            response = await self.model_call(request)
            return response.reply
        call = lambda: self.model.complete(pack.messages, self.tools.schemas())
        if self.resilience is not None:
            return await self.resilience.call(call)
        return await call()

    async def execute(self, step: Step, state: State) -> ActionResult:
        if not step.tool_name:
            return ActionResult(
                step_id=step.id,
                ok=True,
                output=step.instruction,
                tool_name=None,
            )
        try:
            call = lambda: self.tools.invoke(ToolCall(step.tool_name, step.args))
            if self.resilience is not None:
                output = await self.resilience.call(call)
            else:
                output = await call()
        except ToolError as exc:
            return ActionResult(
                step_id=step.id,
                ok=False,
                output="",
                error=str(exc),
                tool_name=step.tool_name,
            )
        return ActionResult(
            step_id=step.id,
            ok=True,
            output=output,
            tool_name=step.tool_name,
        )
