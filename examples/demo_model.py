"""examples 共用的离线演示模型（用户侧代码，不属于框架包）。

框架包不携带测试替身；这里给 examples 提供两个离线工具：

* ``FakeModel``            协议完整的离线模型（按剧本回包，usage 归一化）
* ``answer``/``tool_call`` 构造 ModelReply 的简写
* ``script_model_handler`` 剧本回放 handler：经
  ``interpret(..., extra_handlers={"model": ...})`` 覆盖内置 model 效应
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from harness.contracts.errors import EffectError
from harness.contracts.types import ModelDelta, ModelReply, ToolCall, usage_total

__all__ = ["FakeModel", "answer", "tool_call", "script_model_handler"]


@dataclass
class FakeModel:
    """协议完整的离线模型：complete/stream/usage 归一化。"""

    replies: list[ModelReply | str]
    calls: int = 0
    seen: list[list[dict]] = field(default_factory=list)

    async def complete(self, messages, tools=None, *, response_format=None) -> ModelReply:
        self.calls += 1
        self.seen.append(list(messages))
        index = min(self.calls - 1, len(self.replies) - 1)
        reply = self.replies[index]
        if isinstance(reply, str):
            return ModelReply(content=reply, usage={"input": 0, "output": 0, "total": 0})
        if not reply.usage:
            return ModelReply(
                content=reply.content, tool_calls=reply.tool_calls,
                usage={"input": 0, "output": 0, "total": 0},
                finish_reason=reply.finish_reason, parsed=reply.parsed,
            )
        return reply

    def stream(self, messages, tools=None) -> AsyncIterator[ModelDelta]:
        async def _gen() -> AsyncIterator[ModelDelta]:
            reply = await self.complete(messages, tools)
            if reply.content:
                yield ModelDelta(kind="text", text=reply.content)
            for call in reply.tool_calls:
                yield ModelDelta(kind="tool_call", text=call.name,
                                 index=len(reply.tool_calls))
            yield ModelDelta(kind="usage", usage=dict(reply.usage))

        return _gen()


def tool_call(name: str, **args) -> ModelReply:
    return ModelReply(tool_calls=[ToolCall(name=name, args=args)])


def answer(text: str) -> ModelReply:
    return ModelReply(content=text)


async def script_model_handler(effect, state) -> dict[str, Any]:
    """剧本回放 handler（覆盖内置 model 效应），语义与 tests/support.py 相同。"""
    script = state.data.get("script")
    if script is None:
        raise EffectError("剧本回放需要 state.data['script']")
    cursor = int(state.journal.get("cursor", 0))
    reply = script[cursor] if cursor < len(script) else {"content": "done"}
    state.journal["cursor"] = cursor + 1
    usage = {"total": usage_total(reply.get("usage") if isinstance(reply, dict) else None)}
    return {"ok": True, "output": reply,
            "_usage": {"calls": 1, "tokens": usage["total"]}}
