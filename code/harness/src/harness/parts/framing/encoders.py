"""编码器（SPEC M6.3）：Frame → 载荷。不决定留哪条。"""

from __future__ import annotations

import json
from typing import Any

from harness.contracts.types import Card, Frame, Pack


class ChatEncoder:
    """把帧编成 chat 消息：system 段合并，history 串联，goal 作最后一条 user。

    v3.1（SUPPLEMENT A6）：可注入 TokenCounter 精确计数 Pack.usage 的
    estimated_tokens；缺省沿用取景器的 tokens_est（字符估算口径）。
    与厂商回传 usage 的偏差由此可量化（推导 §5.5 约束 5）。"""

    def __init__(self, fmt: str = "openai", *, counter: Any = None) -> None:
        self.fmt = fmt
        self.counter = counter

    async def encode(self, frame: Frame) -> Pack:
        system_parts = [
            s.text for s in frame.sections if s.name not in ("history", "goal") and s.text
        ]
        history = frame.meta.get("messages") or []
        goal = frame.meta.get("goal") or ""

        messages: list[dict[str, Any]] = []
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.extend(dict(m) for m in history)
        if goal:
            messages.append({"role": "user", "content": goal})

        if self.counter is not None:
            estimated = int(self.counter.count_messages(messages))
        else:
            estimated = frame.tokens_est

        return Pack(
            messages=messages,
            usage={
                "system_chars": sum(len(p) for p in system_parts),
                "history_chars": sum(len(str(m.get("content", ""))) for m in history),
                "task_chars": len(goal),
                "estimated_tokens": estimated,
            },
            dropped=list(frame.dropped),
            frame=frame,
        )


class CardEncoder:
    """把帧编成给人看的卡片。"""

    def __init__(self, fmt: str = "ui") -> None:
        self.fmt = fmt

    async def encode(self, frame: Frame) -> Card:
        return Card(
            title=f"{frame.kind} 帧",
            body="\n\n".join(s.text for s in frame.sections if s.text),
            fields={"sections": str(len(frame.sections)), "dropped": str(len(frame.dropped))},
            actions=(),
        )


class JsonlEncoder:
    """把帧编成一行 JSON（追踪、日志）。"""

    def __init__(self, fmt: str = "jsonl") -> None:
        self.fmt = fmt

    async def encode(self, frame: Frame) -> str:
        return json.dumps(
            {
                "kind": str(frame.kind),
                "tokens_est": frame.tokens_est,
                "dropped": list(frame.dropped),
                "sections": [
                    {"name": s.name, "priority": s.priority, "source": s.source,
                     "tokens": s.tokens_est, "ephemeral": s.ephemeral}
                    for s in frame.sections
                ],
            },
            ensure_ascii=False,
        )


__all__ = ["ChatEncoder", "CardEncoder", "JsonlEncoder"]
