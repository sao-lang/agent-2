"""事件出口（EventSink 实现）：唯一的对外观察面。

只记录结构化 ``RunEvent``，不参与决策；处理异常由调用方兜底、不影响请求。

旧的 ``TraceEvent`` + Tracer span 制已并入这里（AUDIT BL-4：事件单轨）：
span 语义（start_ms/end_ms/parent_id）由 ``RunEvent`` 统一承载，JSONL 行形状
与 ``RunEvent`` 字段一一对应（``ts_ms`` 取代 start/end_ms）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.contracts.types import RunEvent

__all__ = ["NullSink", "MemorySink", "JsonlSink"]


class NullSink:
    """显式无观测出口。"""

    async def emit(self, event: RunEvent) -> None:
        return None


class MemorySink:
    """内存收集；测试与断言用。"""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


class JsonlSink:
    """JSONL 追加写；行形状与 ``RunEvent`` 对齐。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def emit(self, event: RunEvent) -> None:
        row = {
            "trace_id": event.trace_id,
            "span_id": event.span_id,
            "parent_id": event.parent_id,
            "name": event.name,
            "kind": event.kind,
            "ts_ms": event.ts_ms,
            "fields": event.fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
