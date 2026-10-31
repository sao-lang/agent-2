"""测试替身：无模型、无网络。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import ModelReply, ToolCall


@dataclass
class FakeModel:
    replies: list[ModelReply | str]
    calls: int = 0
    seen: list[list[dict]] = field(default_factory=list)

    async def complete(self, messages, tools=None) -> ModelReply:
        self.calls += 1
        self.seen.append(list(messages))
        index = min(self.calls - 1, len(self.replies) - 1)
        reply = self.replies[index]
        if isinstance(reply, str):
            return ModelReply(content=reply)
        return reply


def tool_call(name: str, **args) -> ModelReply:
    return ModelReply(tool_calls=[ToolCall(name=name, args=args)])


def answer(text: str) -> ModelReply:
    return ModelReply(content=text)
