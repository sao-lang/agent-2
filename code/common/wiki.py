"""第 23~24 章产出：LLMWiki（结构化知识层）。

为什么需要 wiki，而不是纯向量库？
  向量库擅长"找到相似片段"，但这三类问题它答不了：
    1. 定义类："XX 到底是什么？我们内部怎么定义？"（答案需要归纳多段）
    2. 口径类："这个指标怎么算？和上个季度有什么区别？"（需要版本）
    3. 矛盾类："文档 A 说 7 天，文档 B 说 15 天，哪个对？"（需要冲突检测）

  wiki 的价值：**把散落的片段沉淀成"有立场、有版本、有来源"的条目。**

设计要点：
  · 条目 = 结构化（不是一段自由文本）
  · 每条结论必须有 source（可溯源）
  · 变更必须有版本与审核（谁改的、为什么改）
  · 必须能做矛盾检测（新旧条目冲突）
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EntryType(str, Enum):
    CONCEPT = "concept"      # 概念/定义
    RULE = "rule"            # 规则/政策
    PROCEDURE = "procedure"  # 流程/SOP
    DECISION = "decision"    # 决策记录（为什么这么做）
    TERM = "term"            # 术语/口径


class EntryStatus(str, Enum):
    DRAFT = "draft"          # 草稿（模型生成，未审核）
    REVIEWING = "reviewing"  # 待审核
    PUBLISHED = "published"  # 已发布（可被检索）
    OUTDATED = "outdated"    # 已过期
    REJECTED = "rejected"    # 已拒绝


@dataclass
class WikiEntry:
    """一条 wiki 条目。

    为什么不是"一段文本"？
    因为自由文本无法回答"这条结论的依据是什么"，
    而 wiki 的全部价值就在于**可追溯、可审核、可对比**。
    """

    id: str
    title: str
    type: EntryType
    definition: str                    # 一句话定义（必须能独立理解）
    key_points: list[str] = field(default_factory=list)      # 要点
    exceptions: list[str] = field(default_factory=list)      # 例外/反例（最容易被漏）
    sources: list[str] = field(default_factory=list)         # 来源（chunk_id / URL / 文档名）
    related: list[str] = field(default_factory=list)         # 关联条目 id
    tags: list[str] = field(default_factory=list)
    status: EntryStatus = EntryStatus.DRAFT
    version: int = 1
    superseded_by: str | None = None
    author: str = "system"
    reviewers: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # 质量信号
    hit_count: int = 0                 # 被检索命中的次数
    helpful_votes: int = 0
    outdated_reports: int = 0

    def render(self) -> str:
        """渲染成喂给模型的文本。

        注意结构：定义在最前（模型最先看到），例外紧随其后
        （因为模型最容易忽略例外），来源放最后（用于引用）。
        """
        parts = [f"# {self.title}", self.definition]
        if self.key_points:
            parts.append("## 要点\n" + "\n".join(f"- {p}" for p in self.key_points))
        if self.exceptions:
            parts.append("## 例外\n" + "\n".join(f"- {e}" for e in self.exceptions))
        if self.sources:
            parts.append("## 来源\n" + "\n".join(f"- {s}" for s in self.sources))
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["status"] = self.status.value
        return d


# ============================================================ 存储

class WikiStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, title TEXT, type TEXT, definition TEXT,
                payload TEXT, status TEXT, version INTEGER,
                superseded_by TEXT, tenant_id TEXT, created_at REAL, updated_at REAL
            )"""
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_wiki_scope ON entries(tenant_id, status)")
        self.conn.commit()

    def upsert(self, e: WikiEntry, tenant_id: str = "default") -> str:
        self.conn.execute(
            """INSERT OR REPLACE INTO entries
               (id,title,type,definition,payload,status,version,superseded_by,tenant_id,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (e.id, e.title, e.type.value, e.definition, json.dumps(e.to_dict(), ensure_ascii=False),
             e.status.value, e.version, e.superseded_by, tenant_id, e.created_at, e.updated_at),
        )
        self.conn.commit()
        return e.id

    def get(self, entry_id: str) -> WikiEntry | None:
        row = self.conn.execute("SELECT payload FROM entries WHERE id=?", (entry_id,)).fetchone()
        return _load(row[0]) if row else None

    def refresh(self, e: WikiEntry, tenant_id: str = "default") -> WikiEntry:
        """从库里重新读一遍后再改。

        `get()` 返回的是 payload 反序列化出来的**新对象**，
        在它上面改字段再 upsert，覆盖的是"读出来那一刻"的整份数据——
        并发时会把别人的更新（比如刚发布的 v2）一起冲掉。
        所以改条目统一走这里：读 → 改 → 写。
        """
        cur = self.get(e.id)
        target = cur or e
        target.status = e.status
        target.superseded_by = e.superseded_by
        target.updated_at = time.time()
        self.upsert(target, tenant_id)
        return target

    def list(
        self,
        status: EntryStatus | None = None,
        type_: EntryType | None = None,
        tenant_id: str = "default",
        include_superseded: bool = False,
    ) -> list[WikiEntry]:
        sql = "SELECT payload FROM entries WHERE tenant_id=?"
        args: list[Any] = [tenant_id]
        if status:
            sql += " AND status=?"
            args.append(status.value)
        if type_:
            sql += " AND type=?"
            args.append(type_.value)
        if not include_superseded:
            sql += " AND (superseded_by IS NULL OR superseded_by='')"
        return [_load(r[0]) for r in self.conn.execute(sql, args).fetchall()]

    def close(self) -> None:
        self.conn.close()


def _load(payload: str) -> WikiEntry:
    d = json.loads(payload)
    d["type"] = EntryType(d["type"])
    d["status"] = EntryStatus(d["status"])
    return WikiEntry(**d)


# ============================================================ 生成（从片段到条目）

EXTRACT_PROMPT = """把下面的文档片段整理成一条 wiki 条目。

要求：
1. definition：一句话说清"是什么"，必须能独立理解（不依赖上下文）
2. key_points：3~5 条要点，每条必须是事实陈述，不要复述原文
3. exceptions：**必须主动找出例外和反例**（如"不适用""除…之外""另见"），
   没有就留空数组——但你要先仔细找
4. 不要编造来源，只使用给定片段

片段：
{chunks}

输出 JSON：
{{"title": "...", "definition": "...", "key_points": [...], "exceptions": [...], "tags": [...]}}"""


def extract_entry_llm(llm: Any, chunks: list[str], type_: EntryType = EntryType.CONCEPT) -> dict:
    """用模型把片段整理成条目结构。"""
    prompt = EXTRACT_PROMPT.format(chunks="\n---\n".join(chunks))
    raw = str(llm.invoke(prompt).content)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {}


def extract_entry_rule(chunks: list[str], title: str, type_: EntryType = EntryType.RULE) -> WikiEntry:
    """规则版抽取（离线可跑）：用句式模板 + 关键词找例外。

    规则版的召回率低，但有两个不可替代的优点：
      1. 可复现（实验对比才可靠）
      2. 零成本（可以先跑全量，再挑重点给模型精修）
    """
    text = "\n".join(chunks)

    # 找例外：这是最容易被忽略、也最有价值的部分
    exceptions: list[str] = []
    for pat in (
        r"[^。；\n]{0,24}不适用[^。；\n]{0,30}",
        r"[^。；\n]{0,20}除[^。；\n]{0,30}",
        r"[^。；\n]{0,20}另见[^。；\n]{0,30}",
        r"[^。；\n]{0,20}不返还[^。；\n]{0,20}",
        r"[^。；\n]{0,20}除外[^。；\n]{0,20}",
    ):
        exceptions.extend(m.group(0).strip() for m in re.finditer(pat, text))

    # 找数字型事实（天数、金额、时效）——这类最容易过时，必须进要点
    facts = re.findall(r"[^。；\n]{0,30}\d+[^。；\n]{0,20}(?:天|日|小时|元|个工作日)[^。；\n]{0,20}", text)

    sentences = [s.strip() for s in re.split(r"[。\n]", text) if len(s.strip()) > 8]
    definition = sentences[0] if sentences else text[:80]

    return WikiEntry(
        id=f"w-{abs(hash(title)) % 10**8}",
        title=title,
        type=type_,
        definition=definition,
        key_points=list(dict.fromkeys(facts))[:5] or sentences[1:6],
        exceptions=list(dict.fromkeys(exceptions))[:5],
        sources=[],
        tags=[],
        status=EntryStatus.DRAFT,
    )


# ============================================================ 矛盾检测

NEGATIONS = ("不", "禁止", "无需", "不支持", "不适用", "不予", "不得", "未", "否")


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def _polarity(text: str) -> bool:
    """粗略判断陈述的极性：True = 肯定，False = 否定。"""
    return not any(n in text for n in NEGATIONS)


def conflict(old: WikiEntry, new_definition: str) -> dict[str, Any]:
    """矛盾检测：三个信号。

    1. 极性翻转（"可以" vs "不可以"）——最严重
    2. 数字不同（7 天 vs 15 天）——次严重
    3. 主题相似度低（说的可能不是同一件事）——需人工看

    真实系统用 NLI 模型判断"这两句是否矛盾"，这里给出可解释的近似。

    ⚠️ 我的第一版有 bug：极性判断把否定词当成"整句变负"，
       但中文里"不适用"和"可申请"出现在同一句是常态，
       结果"不可申请"被判成"肯定"。改成**只比对定义句开头的主谓结构**。
    """
    old_text = old.definition
    new_text = new_definition

    def polarity(text: str) -> bool:
        """只看定义句里"能不能做"的那半句。"""
        head = text.split("，")[0]          # 取第一个逗号前的主句
        return not any(n in head for n in NEGATIONS)

    pol_old, pol_new = polarity(old_text), polarity(new_text)
    nums_old, nums_new = set(_numbers(old_text)), set(_numbers(new_text))

    signals = {
        "polarity_flip": pol_old != pol_new,
        "number_mismatch": bool(nums_old and nums_new and nums_old != nums_new),
        "old_numbers": sorted(nums_old),
        "new_numbers": sorted(nums_new),
    }

    score = 0
    if signals["polarity_flip"]:
        score += 2
    if signals["number_mismatch"]:
        score += 2

    # 主题相似度：字符集合 Jaccard（粗但稳定）
    inter = set(old_text) & set(new_text)
    union = set(old_text) | set(new_text)
    jaccard = len(inter) / len(union) if union else 0
    signals["topic_similarity"] = round(jaccard, 2)

    # 主题相似 → 才谈得上"矛盾"；不相似说明是新条目，不是冲突
    if jaccard >= 0.5:
        score += 1
        # 主句结构相似但结论相反 → 强烈怀疑
        if pol_old != pol_new:
            score += 1

    signals["score"] = score
    signals["needs_review"] = score >= 2
    return signals


# ============================================================ 生命周期

def publish(store: WikiStore, entry_id: str, reviewer: str, tenant_id: str = "default") -> WikiEntry | None:
    """把条目置为 published。

    ⚠️ 发布一条"新版本"时，必须把**同主题的旧版本**一起置为 outdated，
    否则检索会同时命中两版（第 31 章 step3 实测：v1 7 天和 v2 15 天并列返回）。
    这里按"id 去掉 -vN 后缀"识别同主题版本。
    """
    e = store.get(entry_id)
    if e is None:
        return None
    e.status = EntryStatus.PUBLISHED
    e.reviewers.append(reviewer)
    e.updated_at = time.time()
    store.upsert(e, tenant_id)

    root = re.sub(r"-v\d+$", "", e.id)
    for other in store.list(include_superseded=True, tenant_id=tenant_id):
        if other.id == e.id or other.status is not EntryStatus.PUBLISHED:
            continue
        if re.sub(r"-v\d+$", "", other.id) != root:
            continue
        other.status = EntryStatus.OUTDATED
        other.superseded_by = e.id
        store.upsert(other, tenant_id)
    return e


def revise(
    store: WikiStore,
    old_id: str,
    new_definition: str,
    reviewer: str,
    tenant_id: str = "default",
    auto_approve: bool = False,
) -> dict[str, Any]:
    """修订条目：版本 +1，旧的标 superseded，并做矛盾检测。

    为什么"修订"要单独做成一个函数？
    因为它是 wiki 最容易出事故的地方：
      · 旧的没标过期 → 检索到两个版本，答案摇摆
      · 冲突没检测 → 悄悄改掉了关键数字（7 天 → 15 天）
    """
    old = store.get(old_id)
    if old is None:
        return {"ok": False, "reason": "not_found"}

    sig = conflict(old, new_definition)
    new = WikiEntry(
        id=f"{old.id}-v{old.version + 1}",
        title=old.title,
        type=old.type,
        definition=new_definition,
        key_points=old.key_points,
        exceptions=old.exceptions,
        sources=old.sources,
        related=old.related,
        tags=old.tags,
        status=EntryStatus.PUBLISHED if (auto_approve and not sig["needs_review"]) else EntryStatus.REVIEWING,
        version=old.version + 1,
        reviewers=[reviewer],
        created_at=old.created_at,
        updated_at=time.time(),
    )
    store.upsert(new, tenant_id)

    if new.status is EntryStatus.PUBLISHED:
        old.superseded_by = new.id
        old.status = EntryStatus.OUTDATED
        store.upsert(old, tenant_id)

    return {"ok": True, "new_id": new.id, "status": new.status.value,
            "conflict": sig, "auto_approved": new.status is EntryStatus.PUBLISHED}


# ============================================================ 检索

def score_entry(e: WikiEntry, query: str, now: float | None = None) -> float:
    """条目打分：相关度 × 质量信号 × 时效。

    和质量信号挂钩是 wiki 相对纯 RAG 的独特优势：
    你能量化"这条条目被用过多少次、有没有被举报过时"。
    """
    now = now or time.time()
    qset = set(query)
    text = e.render()
    overlap = len(qset & set(text)) / max(len(qset), 1)

    age_days = (now - e.updated_at) / 86400
    freshness = 0.97 ** age_days                     # 缓慢衰减

    quality = (1 + e.helpful_votes * 0.1) / (1 + e.outdated_reports * 0.5)
    usage = 1 + min(e.hit_count, 100) * 0.01

    return overlap * freshness * quality * usage


def search(store: WikiStore, query: str, top_k: int = 3, tenant_id: str = "default") -> list[tuple[WikiEntry, float]]:
    entries = store.list(status=EntryStatus.PUBLISHED, tenant_id=tenant_id)
    scored = [(e, score_entry(e, query)) for e in entries]
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]
