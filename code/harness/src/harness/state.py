"""State 信封：公共字段 + 命名空间 data。"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from .contracts import Goal, RunStatus, SessionRef


@dataclass
class State:
    goal: Goal
    session: SessionRef
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    data: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_index: int = 0
    status: RunStatus = RunStatus.RUNNING
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    last_error: str | None = None

    def section(self, name: str) -> dict[str, Any]:
        """取一个策略自己的命名空间，不存在就建。"""
        value = self.data.get(name)
        if not isinstance(value, dict):
            value = {}
            self.data[name] = value
        return value

    def add_usage(self, tokens: int = 0, calls: int = 0) -> None:
        self.usage["tokens"] += max(0, tokens)
        self.usage["calls"] += max(0, calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": {
                "text": self.goal.text,
                "user_id": self.goal.user_id,
                "session_id": self.goal.session_id,
                "metadata": self.goal.metadata,
            },
            "session": {
                "session_id": self.session.session_id,
                "tenant": self.session.tenant,
                "started_at": self.session.started_at,
            },
            "trace_id": self.trace_id,
            "data": _jsonable(self.data),
            "messages": _jsonable(self.messages),
            "step_index": self.step_index,
            "status": str(self.status),
            "usage": dict(self.usage),
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "State":
        goal = raw["goal"]
        session = raw["session"]
        return cls(
            goal=Goal(**goal),
            session=SessionRef(**session),
            trace_id=raw.get("trace_id", uuid.uuid4().hex),
            data=raw.get("data", {}),
            messages=raw.get("messages", []),
            step_index=int(raw.get("step_index", 0)),
            status=RunStatus(raw.get("status", "running")),
            usage=raw.get("usage", {"tokens": 0, "calls": 0}),
            last_error=raw.get("last_error"),
        )


def _jsonable(value: Any) -> Any:
    """只允许 JSON 能表达的东西进 State；其余类型报错。"""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=_default))
    except TypeError as exc:  # pragma: no cover - 由调用方触发
        raise TypeError(f"State 只能保存可序列化数据：{exc}") from exc


def _default(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"不可序列化类型：{type(value).__name__}")
