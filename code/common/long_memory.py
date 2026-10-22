"""第 57 章产出：三层长期记忆 + 冲突处理。

三层（业界常用划分）：
  semantic   语义记忆：稳定事实（用户偏好、身份、领域知识）
  episodic   情景记忆：做过什么（可回放的事件）
  procedural 程序记忆：怎么做（成功的流程/SOP）

为什么必须分层？
因为三层的写入时机、淘汰策略、检索方式完全不同：
  · 语义：变化慢，需要去重与冲突处理
  · 情景：只增不改，按时间衰减
  · 程序：需要验证成功才写入，且要版本管理
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MemoryKind(str, Enum):
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"


@dataclass
class Memory:
    id: str
    kind: MemoryKind
    key: str  # 语义记忆的去重键（如 "pref.mango"）；情景/程序可为空
    content: str
    tenant_id: str = "default"     # ← 多租户隔离，必须有
    user_id: str = "default"       # ← 用户隔离，必须有
    importance: float = 0.5        # 0~1，影响检索与淘汰
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    use_count: int = 0
    source: str = ""               # 来源（哪次对话/哪个文档）
    tags: list[str] = field(default_factory=list)
    superseded_by: str | None = None  # 被哪条新记忆取代（软删除）


# ============================================================ 存储

class MemoryStore:
    """SQLite 实现（生产可换 Postgres + 向量索引）。

    为什么先用 SQLite？
    因为你要先把**写入策略、冲突处理、淘汰策略**跑通。
    这些逻辑和存储引擎无关，换库时不用重写。
    """

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                key TEXT,
                content TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at REAL,
                last_used_at REAL,
                use_count INTEGER DEFAULT 0,
                source TEXT,
                tags TEXT,
                superseded_by TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_scope ON memories(tenant_id, user_id, kind)")
        self.conn.commit()

    # ---------- 写 ----------

    def write(self, m: Memory) -> str:
        self.conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, kind, key, content, tenant_id, user_id, importance,
                created_at, last_used_at, use_count, source, tags, superseded_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                m.id, m.kind.value, m.key, m.content, m.tenant_id, m.user_id, m.importance,
                m.created_at, m.last_used_at, m.use_count, m.source,
                json.dumps(m.tags, ensure_ascii=False), m.superseded_by,
            ),
        )
        self.conn.commit()
        return m.id

    def supersede(self, old_id: str, new_id: str) -> None:
        """软删除旧记忆。

        为什么软删除而不是 DELETE？
        因为你要能回答"为什么它现在认为我不喜欢芒果了"——
        需要看到"旧记忆是什么时候被什么取代的"。
        """
        self.conn.execute("UPDATE memories SET superseded_by=? WHERE id=?", (new_id, old_id))
        self.conn.commit()

    # ---------- 读 ----------

    def query(
        self,
        kind: MemoryKind | None = None,
        tenant_id: str = "default",
        user_id: str = "default",
        include_superseded: bool = False,
    ) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE tenant_id=? AND user_id=?"
        args: list[Any] = [tenant_id, user_id]
        if kind:
            sql += " AND kind=?"
            args.append(kind.value)
        if not include_superseded:
            sql += " AND superseded_by IS NULL"
        rows = self.conn.execute(sql, args).fetchall()
        cols = [d[0] for d in self.conn.execute("SELECT * FROM memories LIMIT 0").description]
        return [_row_to_mem(dict(zip(cols, r))) for r in rows]

    def find_by_key(self, key: str, **scope) -> Memory | None:
        ms = [m for m in self.query(**scope) if m.key == key]
        return ms[0] if ms else None

    def close(self) -> None:
        self.conn.close()


def _row_to_mem(d: dict) -> Memory:
    return Memory(
        id=d["id"],
        kind=MemoryKind(d["kind"]),
        key=d["key"] or "",
        content=d["content"],
        tenant_id=d["tenant_id"],
        user_id=d["user_id"],
        importance=d["importance"],
        created_at=d["created_at"],
        last_used_at=d["last_used_at"],
        use_count=d["use_count"],
        source=d["source"] or "",
        tags=json.loads(d["tags"] or "[]"),
        superseded_by=d["superseded_by"],
    )


# ============================================================ 冲突检测

def conflict_ratio(a: str, b: str) -> float:
    """粗略的冲突度量：字面重合度低但主题相同 → 可疑冲突。

    真实实现用 NLI 模型（"这两句是否矛盾"）。
    这里给出一个可解释的近似，用于演示流程。
    """
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    jaccard = len(sa & sb) / len(sa | sb)
    return 1 - jaccard


@dataclass
class MemoryWriter:
    """写入策略：决定"什么值得记"以及"和旧记忆冲突怎么办"。"""

    store: MemoryStore
    min_importance: float = 0.3

    def write_semantic(
        self,
        key: str,
        content: str,
        importance: float,
        **scope: Any,
    ) -> dict[str, Any]:
        """写语义记忆（有去重和冲突处理）。"""
        if importance < self.min_importance:
            return {"action": "skip", "reason": f"重要性 {importance:.2f} 低于阈值"}

        existing = self.store.find_by_key(key, **scope)
        if existing is None:
            m = Memory(id=f"mem-{time.time_ns()}", kind=MemoryKind.SEMANTIC, key=key,
                       content=content, importance=importance, **scope)
            self.store.write(m)
            return {"action": "created", "id": m.id}

        if existing.content == content:
            # 完全重复：只更新使用计数与时间，不新增
            existing.use_count += 1
            existing.last_used_at = time.time()
            self.store.write(existing)
            return {"action": "touched", "id": existing.id}

        # 内容不同 → 冲突
        ratio = conflict_ratio(existing.content, content)
        new = Memory(id=f"mem-{time.time_ns()}", kind=MemoryKind.SEMANTIC, key=key,
                     content=content, importance=importance, **scope)
        self.store.write(new)
        self.store.supersede(existing.id, new.id)
        return {
            "action": "superseded",
            "old_id": existing.id,
            "old_content": existing.content,
            "new_id": new.id,
            "conflict_ratio": round(ratio, 2),
            # 高冲突时必须人工确认 —— 见第 32 章
            "needs_review": ratio > 0.6,
        }

    def write_episodic(self, content: str, importance: float = 0.5, **scope: Any) -> str:
        """写情景记忆（只增不改）。"""
        m = Memory(id=f"epi-{time.time_ns()}", kind=MemoryKind.EPISODIC, key="",
                   content=content, importance=importance, **scope)
        return self.store.write(m)

    def write_procedural(self, name: str, steps: list[str], success: bool, **scope: Any) -> str | None:
        """写程序记忆（只在成功时写入，且版本化）。

        为什么不记失败的流程？
        因为"失败的流程"信息价值低（你不能照着做），而且会污染检索。
        失败的教训应该进 Reflexion 的 lessons（第 34 章），不是程序记忆。
        """
        if not success:
            return None
        m = Memory(id=f"proc-{time.time_ns()}", kind=MemoryKind.PROCEDURAL, key=name,
                   content=json.dumps(steps, ensure_ascii=False), importance=0.8, **scope)
        # 同名流程：旧的标为被取代
        old = self.store.find_by_key(name, kind=MemoryKind.PROCEDURAL, **scope)
        self.store.write(m)
        if old:
            self.store.supersede(old.id, m.id)
        return m.id


# ============================================================ 检索与淘汰

def score_memory(m: Memory, now: float | None = None, halflife_days: float = 30.0) -> float:
    """记忆打分：重要性 × 时间衰减 × 使用频率。

    score = importance * 0.5^(age/halflife) * (1 + log(1+use_count))

    为什么要有时间衰减？
    因为"用户三个月前说过喜欢蓝色"不应该和"昨天说喜欢黑色"等价。
    """
    now = now or time.time()
    age_days = (now - m.created_at) / 86400
    recency = 0.5 ** (age_days / halflife_days)
    freq = 1 + math.log1p(m.use_count)
    return m.importance * recency * freq


def retrieve(
    store: MemoryStore,
    limit: int = 5,
    kind: MemoryKind | None = None,
    **scope: Any,
) -> list[tuple[Memory, float]]:
    ms = store.query(kind=kind, **scope)
    scored = [(m, score_memory(m)) for m in ms]
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def prune(store: MemoryStore, keep: int = 50, **scope: Any) -> int:
    """淘汰：保留分数最高的 keep 条，其余软删除。

    生产里删除要谨慎——建议先标记，观察一段时间再物理删除。
    """
    ms = store.query(**scope)
    scored = sorted(((m, score_memory(m)) for m in ms), key=lambda x: -x[1])
    to_drop = scored[keep:]
    for m, _ in to_drop:
        store.supersede(m.id, "PRUNED")
    return len(to_drop)
