"""存储协议（SPEC M7.2、M11）。

v1 形状（`Durability`/`Memory`）保留兼容；v2 形状（`CheckpointStore`/`MemoryStore`
等）在 P3 接实现。两者并存是有意的：每个方法都能用 `Namespace` 做隔离。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, Sequence, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.state import State
    from harness.contracts.types import (
        Checkpoint,
        Namespace,
        Recalled,
        SessionMeta,
        SessionRef,
    )


@runtime_checkable
class Durability(Protocol):
    """v1 检查点：save/load。违反"历史不可变"，P3 迁移到 `CheckpointStore`。"""

    async def save(self, state: "State") -> None: ...

    async def load(self, session_id: str) -> "State | None": ...


@runtime_checkable
class CheckpointStore(Protocol):
    """v2 多版本快照：追加新 rev，旧版本永不修改（不变量 1）。"""

    async def put(
        self, ns: "Namespace", sid: str, state: "State", *, expect_rev: int | None
    ) -> int: ...

    async def get(self, ns: "Namespace", sid: str, rev: int | None = None) -> "Checkpoint | None": ...

    async def history(self, ns: "Namespace", sid: str, *, limit: int = 50) -> list[int]: ...


@runtime_checkable
class SessionStore(Protocol):
    async def create(self, ns: "Namespace", meta: "SessionMeta") -> "SessionMeta": ...

    async def get(self, ns: "Namespace", sid: str) -> "SessionMeta | None": ...

    async def list(self, ns: "Namespace", *, cursor: str | None = None, limit: int = 50) -> Any: ...

    async def update(self, ns: "Namespace", sid: str, patch: dict[str, Any]) -> "SessionMeta": ...


@runtime_checkable
class MessageLog(Protocol):
    async def append(self, ns: "Namespace", sid: str, msgs: Sequence[dict]) -> int: ...

    async def tail(self, ns: "Namespace", sid: str, *, max_tokens: int) -> list[dict]: ...


@runtime_checkable
class Memory(Protocol):
    """v1 形状，保留兼容。"""

    async def recall(
        self, query: str, *, scope: str, layers: list[str], k: int
    ) -> list["Recalled"]: ...

    async def write(self, items: list["Recalled"]) -> int: ...


@runtime_checkable
class MemoryStore(Protocol):
    """v2 形状：命名空间强制、可遗忘、可过期、去重键（SPEC M7.2）。"""

    async def recall(
        self, ns: "Namespace", query: str, *, layers: Sequence[str], k: int
    ) -> list["Recalled"]: ...

    async def upsert(self, ns: "Namespace", items: Sequence["Recalled"]) -> int: ...

    async def forget(self, ns: "Namespace", ids: Sequence[str]) -> int: ...

    async def expire(self, ns: "Namespace", now: datetime) -> int: ...


@runtime_checkable
class Idempotency(Protocol):
    async def begin(self, ns: "Namespace", key: str) -> Any: ...

    async def commit(self, ns: "Namespace", key: str, value: Any) -> None: ...


@runtime_checkable
class MemoryPolicy(Protocol):
    """写入策略与存取分离（SPEC M7.2）：该不该写、写成什么、何时合并失效。"""

    async def should_write(self, state: "State", result: Any) -> bool: ...

    async def extract(self, state: "State") -> list["Recalled"]: ...

    async def merge(
        self, old: list["Recalled"], new: list["Recalled"]
    ) -> list["Recalled"]: ...

    async def decay(self, items: list["Recalled"], now: datetime) -> list["Recalled"]: ...


__all__ = [
    "Durability",
    "CheckpointStore",
    "SessionStore",
    "MessageLog",
    "Memory",
    "MemoryStore",
    "Idempotency",
    "MemoryPolicy",
]
