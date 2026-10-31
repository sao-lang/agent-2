"""Tracer：唯一的外部事件出口。

只记录结构化事件，不参与决策；处理异常只记日志、不影响请求。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import TraceEvent


class NullTracer:
    async def emit(self, event: TraceEvent) -> None:
        return None


class MemoryTracer:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


class JsonlTracer:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def emit(self, event: TraceEvent) -> None:
        row = {
            "trace_id": event.trace_id,
            "span_id": event.span_id,
            "parent_id": event.parent_id,
            "name": event.name,
            "kind": event.kind,
            "start_ms": event.start_ms,
            "end_ms": event.end_ms,
            "fields": event.fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def new_event(trace_id: str, name: str, *, kind: str = "span",
              parent_id: str | None = None,
              fields: dict[str, Any] | None = None,
              start_ms: int | None = None,
              end_ms: int | None = None) -> TraceEvent:
    now = int(time.time() * 1000)
    return TraceEvent(
        trace_id=trace_id,
        span_id=uuid.uuid4().hex[:12],
        parent_id=parent_id,
        name=name,
        kind=kind,
        start_ms=start_ms if start_ms is not None else now,
        end_ms=end_ms if end_ms is not None else now,
        fields=fields or {},
    )
