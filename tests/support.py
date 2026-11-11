"""测试支持模块：测试替身与离线回放工具的**唯一住址**。

测试替身不进框架包（``src/harness``）——框架包里只有真实实现与
内存/本地实现；本模块供 tests/ 专用，examples 需要离线演示时自带
``examples/demo_model.py``。

* ``FakeModel``      协议完整的离线模型（complete/stream/response_format/usage 归一化）
* ``answer``/``tool_call``  构造 ModelReply 回包的简写
* ``script_model_handler`` 剧本回放 handler：经 ``extra_handlers={"model": ...}``
  覆盖内置 model 效应，按 ``state.data["script"]`` 次序回放，journal cursor
  即时推进（不参与回溯）
* ``FakeSandbox``    剧本沙箱：记录 argv、按预设返回 ExecResult
* ``FakeClock``      可控时钟：钉死时间做回放
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Mapping, Sequence

from harness.contracts.types import ExecResult, Limits, ModelDelta, ModelReply, ToolCall, usage_total

__all__ = [
    "FakeModel", "answer", "tool_call",
    "script_model_handler",
    "FakeSandbox", "FakeClock",
]


# ------------------------------------------------------------------ 离线模型


@dataclass
class FakeModel:
    """协议完整的离线模型：complete/stream/response_format/usage 归一化。

    仅供 tests/ 使用；框架包不携带测试替身。usage 归一化为协议口径
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
            return ModelReply(
                content=reply.content, tool_calls=reply.tool_calls,
                usage={"input": 0, "output": 0, "total": 0},
                finish_reason=reply.finish_reason, parsed=reply.parsed,
            )
        return reply

    def stream(self, messages, tools=None) -> AsyncIterator[ModelDelta]:
        """把 complete 的回包拆成 text + usage 两段增量。"""

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


# ------------------------------------------------------------------ 剧本回放


async def script_model_handler(effect, state) -> dict[str, Any]:
    """剧本回放 handler（覆盖内置 model 效应）。

    用法：``Runtime(..., extra_handlers={"model": script_model_handler})``。
    按 ``state.data["script"]`` 次序回放；超出脚本长度时补
    ``{"content": "done"}``。journal cursor 即时推进——它是"外部世界的
    既成事实"，不参与回溯（回溯撤销状态，不撤销已消费的外部进度）。
    """
    from harness.contracts.errors import EffectError

    script = state.data.get("script")
    if script is None:
        raise EffectError("剧本回放需要 state.data['script']")
    cursor = int(state.journal.get("cursor", 0))
    reply = script[cursor] if cursor < len(script) else {"content": "done"}
    state.journal["cursor"] = cursor + 1
    usage = {"total": usage_total(reply.get("usage") if isinstance(reply, dict) else None)}
    return {"ok": True, "output": reply,
            "_usage": {"calls": 1, "tokens": usage["total"]}}


# ------------------------------------------------------------------ 沙箱 / 时钟


class FakeSandbox:
    """剧本沙箱：记录每次 argv，按预设返回。仅 tests/ 使用。"""

    def __init__(self, script: dict[str, ExecResult] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, ...]] = []
        self.killed: list[str] = []

    async def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str = "/work",
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        limits: Limits | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult:
        key = " ".join(argv)
        self.calls.append(tuple(argv))
        return self.script.get(key, ExecResult(exit=0, stdout=f"fake:{key}"))

    async def kill(self, exec_id: str) -> None:
        self.killed.append(exec_id)


class FakeClock:
    """可控时钟：回放与测试必须能钉死时间。"""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._mono = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds
