"""测试替身：无模型、无网络。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from harness.contracts.types import ModelDelta, ModelReply, ToolCall


@dataclass
class FakeModel:
    """协议完整的离线模型（M06）：complete/stream/response_format/usage 归一化。

    仅供测试与显式 ``model="fake"`` 装配使用；生产预设不再默认指向它
    （F 组：缺真依赖启动期显式报错）。usage 归一化为协议口径
    ``{input, output, total}``，离线回包恒为 0——记账链路拿到的形状
    与真模型一致，数值由测试按需自行构造。
    """

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
            # 数据类回包未带用量时也归一化形状（数值保持 0，不改测试口径）。
            return ModelReply(
                content=reply.content, tool_calls=reply.tool_calls,
                usage={"input": 0, "output": 0, "total": 0},
                finish_reason=reply.finish_reason, parsed=reply.parsed,
            )
        return reply

    def stream(self, messages, tools=None) -> AsyncIterator[ModelDelta]:
        """把 complete 的回包拆成 text + usage 两段增量（M06 协议完整性）。"""

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
