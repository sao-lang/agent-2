"""Durability：一次运行的检查点。

默认内存实现只用于测试；生产用 SQLite（仍是标准库）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .state import State


class NullDurability:
    async def save(self, state: State) -> None:
        return None

    async def load(self, session_id: str) -> State | None:
        return None


class MemoryDurability:
    def __init__(self) -> None:
        self._states: dict[str, dict] = {}

    async def save(self, state: State) -> None:
        self._states[state.session.session_id] = state.to_dict()

    async def load(self, session_id: str) -> State | None:
        raw = self._states.get(session_id)
        return State.from_dict(raw) if raw else None


class SQLiteDurability:
    """单文件检查点；适合单机、桌面应用、示例。"""

    def __init__(self, path: str | Path = "harness-runs.db") -> None:
        self.path = str(path)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "session_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    async def save(self, state: State) -> None:
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs(session_id, state, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(session_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
                (state.session.session_id, payload),
            )

    async def load(self, session_id: str) -> State | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM runs WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return State.from_dict(json.loads(row[0]))
