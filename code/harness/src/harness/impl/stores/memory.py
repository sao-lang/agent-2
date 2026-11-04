"""存储的内存实现（SPEC M11、M7.2）。

五条不变量都由这里体现，测试见 tests/test_stores.py：
    C1 历史不可变   put 只追加新 rev，旧 rev 内容不变
    C2 乐观并发     expect_rev 不匹配 → ConcurrencyError
    C3 命名空间强制 跨 ns 读取视为不存在
    C4 幂等写       同 dedup_key 不产生第二条
    C5 append-only  消息只追加
    C6 尾读有预算   tail(max_tokens) 从尾部往回取
    C7 点查命中     begin 命中返回 Recorded，否则 None
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime
from typing import Any, Sequence

from harness.contracts.errors import ConcurrencyError
from harness.contracts.state import State
from harness.contracts.types import (
    Checkpoint,
    Goal,
    Namespace,
    Page,
    Recalled,
    Recorded,
    SessionMeta,
    SessionRef,
)


def _ns_key(ns: Namespace) -> tuple[str, str, str, str]:
    return ns.as_tuple()


# ------------------------------------------------------------------ 检查点


class MemoryCheckpointStore:
    """C1 + C2 + C3：多版本快照，旧 rev 永不修改。"""

    def __init__(self) -> None:
        self._rows: dict[tuple, list[dict[str, Any]]] = {}

    async def put(
        self, ns: Namespace, sid: str, state: State, *, expect_rev: int | None = None
    ) -> int:
        key = (_ns_key(ns), sid)
        versions = self._rows.setdefault(key, [])
        current = len(versions) - 1
        if expect_rev is not None and expect_rev != current:
            raise ConcurrencyError(f"{sid}: 期望 rev={expect_rev}，实际 rev={current}")
        versions.append(copy.deepcopy(state.to_dict()))   # 深拷贝 = 旧版本不可变
        state.rev = len(versions) - 1
        return state.rev

    async def get(self, ns: Namespace, sid: str, rev: int | None = None) -> Checkpoint | None:
        versions = self._rows.get((_ns_key(ns), sid))
        if not versions:
            return None
        index = len(versions) - 1 if rev is None else rev
        if index < 0 or index >= len(versions):
            return None
        raw = copy.deepcopy(versions[index])
        return Checkpoint(session_id=sid, rev=index, state=State.from_dict(raw))

    async def history(self, ns: Namespace, sid: str, *, limit: int = 50) -> list[int]:
        versions = self._rows.get((_ns_key(ns), sid), [])
        return list(range(len(versions)))[-limit:]


# ------------------------------------------------------------------ 会话


class MemorySessionStore:
    """C3：会话元数据（含配额）。"""

    def __init__(self) -> None:
        self._rows: dict[tuple, SessionMeta] = {}

    async def create(self, ns: Namespace, meta: SessionMeta) -> SessionMeta:
        self._rows[(_ns_key(ns), meta.id)] = meta
        return meta

    async def get(self, ns: Namespace, sid: str) -> SessionMeta | None:
        return self._rows.get((_ns_key(ns), sid))

    async def list(self, ns: Namespace, *, cursor: str | None = None, limit: int = 50) -> Page:
        items = [m for (n, _sid), m in sorted(self._rows.items()) if n == _ns_key(ns)]
        start = int(cursor) if cursor else 0
        window = items[start : start + limit]
        nxt = str(start + limit) if start + limit < len(items) else None
        return Page(items=tuple(window), cursor=nxt)

    async def update(self, ns: Namespace, sid: str, patch: dict[str, Any]) -> SessionMeta:
        key = (_ns_key(ns), sid)
        meta = self._rows.get(key)
        if meta is None:
            raise KeyError(f"未知会话：{sid}")
        updated = replace(meta, **patch)
        self._rows[key] = updated
        return updated


# ------------------------------------------------------------------ 消息


class MemoryMessageLog:
    """C5 + C6：只追加；尾读按 token 预算近似（1 token ≈ 4 字符）。"""

    def __init__(self) -> None:
        self._rows: dict[tuple, list[dict[str, Any]]] = {}

    async def append(self, ns: Namespace, sid: str, msgs: Sequence[dict[str, Any]]) -> int:
        self._rows.setdefault((_ns_key(ns), sid), []).extend(copy.deepcopy(list(msgs)))
        return len(self._rows[(_ns_key(ns), sid)])

    async def tail(self, ns: Namespace, sid: str, *, max_tokens: int) -> list[dict[str, Any]]:
        rows = self._rows.get((_ns_key(ns), sid), [])
        budget = max(1, max_tokens) * 4
        out: list[dict[str, Any]] = []
        used = 0
        for msg in reversed(rows):                      # 从尾部往回取
            size = len(str(msg.get("content", "")))
            if used + size > budget and out:
                break
            out.append(copy.deepcopy(msg))
            used += size
        return list(reversed(out))


# ------------------------------------------------------------------ 幂等


class MemoryIdempotency:
    """C7：点查命中。"""

    def __init__(self) -> None:
        self._rows: dict[tuple, Recorded] = {}

    async def begin(self, ns: Namespace, key: str) -> Recorded | None:
        return self._rows.get((_ns_key(ns), key))

    async def commit(self, ns: Namespace, key: str, value: Recorded) -> None:
        self._rows[(_ns_key(ns), key)] = value


# ------------------------------------------------------------------ 记忆


class MemoryMemoryStore:
    """C3 + C4：命名空间隔离、dedup_key 去重、软删（superseded_by）。

    in-memory 版本用 `age_days >= ttl_days` 近似过期；真实实现用 expires_at 列。
    """

    def __init__(self, *, ttl_days: int = 365) -> None:
        self._rows: dict[tuple, list[Recalled]] = {}
        self.ttl_days = ttl_days

    async def recall(
        self, ns: Namespace, query: str, *, layers: Sequence[str] = (), k: int = 6
    ) -> list[Recalled]:
        rows = [r for r in self._rows.get(_ns_key(ns), []) if not r.superseded_by]
        if layers:
            rows = [r for r in rows if r.layer in layers]
        scored = sorted(rows, key=lambda r: r.score, reverse=True)
        return scored[:k]

    async def upsert(self, ns: Namespace, items: Sequence[Recalled]) -> int:
        key = _ns_key(ns)
        bucket = self._rows.setdefault(key, [])
        written = 0
        for item in items:
            if not item.dedup_key:
                bucket.append(item)
                written += 1
                continue
            # 找同 dedup_key 的当前版本（未被软删的）
            current = next(
                (
                    i
                    for i, r in enumerate(bucket)
                    if r.dedup_key == item.dedup_key and not r.superseded_by
                ),
                None,
            )
            if current is None:                       # 新增
                bucket.append(replace(item, superseded_by=""))
            else:                                     # C4：旧的指向新的，不产生两条当前版本
                old_id = bucket[current].id or bucket[current].dedup_key
                bucket[current] = replace(bucket[current], superseded_by=item.id or item.dedup_key)
                bucket.append(replace(item, superseded_by="", id=item.id or old_id))
            written += 1
        return written

    async def forget(self, ns: Namespace, ids: Sequence[str]) -> int:
        target = set(ids)
        count = 0
        for i, item in enumerate(self._rows.get(_ns_key(ns), [])):
            if item.id in target and not item.superseded_by:
                self._rows[_ns_key(ns)][i] = replace(item, superseded_by="deleted")
                count += 1
        return count

    async def expire(self, ns: Namespace, now: datetime) -> int:
        bucket = self._rows.get(_ns_key(ns), [])
        keep = [r for r in bucket if r.age_days < self.ttl_days]
        removed = len(bucket) - len(keep)
        self._rows[_ns_key(ns)] = keep
        return removed

    async def all_items(self, ns: Namespace) -> list[Recalled]:
        return list(self._rows.get(_ns_key(ns), []))


# ------------------------------------------------------------------ 记忆策略


class ConservativeMemoryPolicy:
    """默认写入策略（SPEC M7.2）：只写结论与偏好，无来源不写，脱敏在前。"""

    def __init__(self, *, max_items: int = 50, ttl_days: int = 365) -> None:
        self.max_items = max_items
        self.ttl_days = ttl_days

    async def should_write(self, state: State, result: Any) -> bool:
        answer = getattr(result, "answer", "") or ""
        return bool(answer.strip()) and getattr(result, "status", "") in {
            "completed",
            "degraded",
        }

    async def extract(self, state: State) -> list[Recalled]:
        answer = state.data.get("last_output") or ""
        if not answer.strip():
            return []
        return [
            Recalled(
                text=str(answer)[:500],
                layer="episodic",
                score=1.0,
                source=f"run:{state.trace_id}",
                dedup_key=f"run:{state.trace_id}",
                id=f"run:{state.trace_id}",
            )
        ]

    async def merge(self, old: list[Recalled], new: list[Recalled]) -> list[Recalled]:
        by_key = {r.dedup_key: r for r in old if r.dedup_key}
        for item in new:
            by_key[item.dedup_key] = item
        return list(by_key.values())

    async def decay(self, items: list[Recalled], now: datetime) -> list[Recalled]:
        return [r for r in items if r.age_days < self.ttl_days][: self.max_items]


__all__ = [
    "MemoryCheckpointStore",
    "MemorySessionStore",
    "MemoryMessageLog",
    "MemoryIdempotency",
    "MemoryMemoryStore",
    "ConservativeMemoryPolicy",
]
