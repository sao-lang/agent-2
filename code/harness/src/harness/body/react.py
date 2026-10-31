"""ReAct：每轮由模型决定下一步；没有显式 Plan。"""

from __future__ import annotations

from ..contracts import Done, Step


class ReactPolicy:
    def __init__(self, max_steps: int = 8) -> None:
        self.max_steps = max_steps

    async def next_step(self, state, ctx) -> Step | Done:
        if state.step_index >= self.max_steps:
            return Done(answer=state.data.get("last_output", ""), reason="max_steps")

        pack = await ctx.context.assemble(state, ctx.budget.remaining_tokens)
        reply = await ctx.actor.decide(state, pack)
        state.data["last_model_usage"] = dict(reply.usage)
        tokens = int(reply.usage.get("total_tokens", 0))
        state.add_usage(tokens=tokens, calls=1)
        ctx.budget.spend(tokens=tokens, calls=1)

        if reply.tool_calls:
            call = reply.tool_calls[0]
            step_id = f"s{state.step_index + 1}"
            state.data["_react_tool_call_id"] = step_id
            return Step(
                id=step_id,
                instruction=reply.content,
                tool_name=call.name,
                args=call.args,
            )

        return Done(answer=reply.content)
