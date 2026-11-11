"""流式护栏（SPEC M9.4）：窗口缓冲 + 增量检测。

三条规则：
    1 窗口缓冲：最近 64 字符不立即下发（防跨块敏感串）
    2 已下发不可撤回：命中只能"中断 + 说明"
    3 块级降级：检测器不支持增量时每 256 字符整块检测
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Sequence

from harness.contracts.status import GuardrailAction
from harness.contracts.types import Content, GuardrailVerdict, StreamState
from harness.parts.guardrail.detectors import arbitrate

WINDOW = 64
BLOCK_SIZE = 256


@dataclass
class StreamOutcome:
    """一次流式运行的结局。"""

    text: str = ""
    blocked: bool = False
    labels: tuple[str, ...] = ()
    blocks: int = 0
    degraded: bool = False
    reason: str = ""


class StreamGuard:
    """包住一个文本增量流，边收边判。

    C04：不再按「有无增量接口」过滤检测器——内置检测器只有 ``check``，
    过滤会把 guardrails 清空、护栏整体空转。现在逐检测器分流：
    有 ``feed`` 用增量语义，否则退化为对当前窗口整块 ``check``。
    """

    def __init__(self, guardrails: Sequence[Any], *, window: int = WINDOW,
                 block_size: int = BLOCK_SIZE) -> None:
        self.guardrails = [g for g in guardrails
                           if callable(getattr(g, "feed", None))
                           or callable(getattr(g, "check", None))]
        self.window = window
        self.block_size = block_size

    async def run(self, deltas: AsyncIterator[str]) -> AsyncIterator[str]:
        """产出可直接下发的文本块；命中 block 时停止产出。"""
        state = StreamState()
        pending = ""
        emitted = 0
        while True:
            try:
                delta = await deltas.__anext__()
            except StopAsyncIteration:
                break

            pending += delta
            verdict = await self._feed(pending, state)
            if verdict.action == GuardrailAction.BLOCK:
                self.outcome = StreamOutcome(blocked=True, labels=verdict.labels,
                                             blocks=state.blocks,
                                             reason="guardrail_blocked_midstream")
                return

            # 窗口缓冲：保留最后 window 个字符不下发
            if len(pending) > self.window:
                cut = len(pending) - self.window
                chunk, pending = pending[:cut], pending[cut:]
                emitted += len(chunk)
                yield chunk

        # flush：把缓冲里剩下的也判一次
        if pending:
            verdict = await self._feed(pending, state)
            if verdict.action == GuardrailAction.BLOCK:
                self.outcome = StreamOutcome(blocked=True, labels=verdict.labels,
                                             blocks=state.blocks,
                                             reason="guardrail_blocked_midstream")
                return
            emitted += len(pending)
            yield pending
        self.outcome = StreamOutcome(text="", blocks=state.blocks, degraded=False)

    async def _feed(self, buffer: str, state: StreamState) -> GuardrailVerdict:
        verdicts = []
        text = buffer[-self.block_size :]
        for rule in self.guardrails:
            try:
                feed = getattr(rule, "feed", None)
                if feed is not None:
                    verdicts.append(await feed(text, state))
                else:
                    # C04：check-only 检测器的退化路径——对当前窗口整块检测。
                    verdicts.append(
                        await rule.check(Content(text=text, kind="stream"))
                    )
            except Exception:  # noqa: BLE001 - 检测器故障默认 fail-closed
                verdicts.append(
                    GuardrailVerdict(risk=1.0, labels=("detector_error",), action="block")
                )
        return arbitrate(verdicts)

    outcome: StreamOutcome = field(default_factory=StreamOutcome)


async def guard_stream(
    deltas: AsyncIterator[str],
    guardrails: Sequence[Any],
) -> AsyncIterator[str]:
    """便捷入口：返回经过护栏过滤的文本流。"""
    guard = StreamGuard(guardrails)
    async for chunk in guard.run(deltas):
        yield chunk


__all__ = ["WINDOW", "BLOCK_SIZE", "StreamOutcome", "StreamGuard", "guard_stream"]
