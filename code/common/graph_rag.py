"""第 32 章产出：GraphRAG 的最小实现。

三个层次，逐级加深：
  1. 实体/关系抽取（离线规则版 + 模型版）
  2. 图构建（邻接表）+ 二跳扩展检索
  3. 社区摘要（GraphRAG 的核心思想：先总结"一个圈子"，再回答全局问题）

为什么需要 GraphRAG？
向量检索是"碎片匹配"，它回答不了：
  · 多跳问题："用了优惠券退货会返还吗" → 需要先知道会员权益，再知道退货规则
  · 聚合问题："这款产品主要有哪些问题" → 答案分散在几十个片段里，没有哪一片是答案
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable


# ============================================================ 图数据结构

@dataclass
class Entity:
    name: str
    type: str = "concept"
    mentions: int = 1
    chunk_ids: set[str] = field(default_factory=set)


@dataclass
class Relation:
    src: str
    rel: str
    dst: str
    weight: int = 1
    chunk_ids: set[str] = field(default_factory=set)


@dataclass
class KnowledgeGraph:
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    _out: dict[str, list[Relation]] = field(default_factory=lambda: defaultdict(list))
    _in: dict[str, list[Relation]] = field(default_factory=lambda: defaultdict(list))

    def add_entity(self, name: str, type_: str = "concept", chunk_id: str | None = None) -> None:
        name = name.strip()
        if not name:
            return
        e = self.entities.get(name)
        if e is None:
            self.entities[name] = Entity(name=name, type=type_)
            e = self.entities[name]
        else:
            e.mentions += 1
        if chunk_id:
            e.chunk_ids.add(chunk_id)

    def add_relation(self, src: str, rel: str, dst: str, chunk_id: str | None = None) -> None:
        self.add_entity(src)
        self.add_entity(dst)
        r = Relation(src=src, rel=rel, dst=dst)
        if chunk_id:
            r.chunk_ids.add(chunk_id)
        self.relations.append(r)
        self._out[src].append(r)
        self._in[dst].append(r)

    # ---------- 查询 ----------

    def neighbors(self, name: str, direction: str = "out") -> list[Relation]:
        if direction == "out":
            return self._out.get(name, [])
        if direction == "in":
            return self._in.get(name, [])
        return self._out.get(name, []) + self._in.get(name, [])

    def expand(self, seeds: Iterable[str], hops: int = 2) -> dict[str, int]:
        """从种子实体出发做 BFS 扩展，返回 {实体: 距离}。

        这就是"多跳检索"的核心：不只看直接相连的，还要看两跳外的。
        为什么是 2 跳？因为 3 跳的噪声会急剧增加（论文里的经验值）。
        """
        dist: dict[str, int] = {}
        q: deque[tuple[str, int]] = deque()
        for s in seeds:
            if s in self.entities:
                dist[s] = 0
                q.append((s, 0))

        while q:
            cur, d = q.popleft()
            if d >= hops:
                continue
            for r in list(self._out.get(cur, [])) + list(self._in.get(cur, [])):
                nxt = r.dst if r.src == cur else r.src
                if nxt not in dist:
                    dist[nxt] = d + 1
                    q.append((nxt, d + 1))
        return dist

    def paths(self, a: str, b: str, max_len: int = 3) -> list[list[str]]:
        """找两个实体之间的路径——"为什么这两个概念相关"的解释。"""
        if a not in self.entities or b not in self.entities:
            return []
        out: list[list[str]] = []
        q: deque[list[str]] = deque([[a]])
        while q:
            path = q.popleft()
            if len(path) > max_len:
                continue
            cur = path[-1]
            if cur == b:
                out.append(path)
                continue
            for r in self.neighbors(cur, "both"):
                nxt = r.dst if r.src == cur else r.src
                if nxt not in path:
                    q.append(path + [nxt])
        return out

    # ---------- 社区（连通分量近似） ----------

    def communities(self) -> list[set[str]]:
        """用连通分量近似"社区"。

        真正的 GraphRAG 用 Leiden 做层次聚类，
        但对教学来说，连通分量已经能说明"为什么社区摘要有效"。
        """
        seen: set[str] = set()
        out: list[set[str]] = []
        for e in self.entities:
            if e in seen:
                continue
            comp: set[str] = set()
            q = deque([e])
            while q:
                cur = q.popleft()
                if cur in comp:
                    continue
                comp.add(cur)
                for r in self.neighbors(cur, "both"):
                    nxt = r.dst if r.src == cur else r.src
                    if nxt not in comp:
                        q.append(nxt)
            seen |= comp
            out.append(comp)
        return out


# ============================================================ 抽取

# 领域词典（真实系统用 NER 模型或 LLM 抽取）
DOMAIN_TERMS = [
    "无理由退货", "质量问题", "运费", "检测费", "换新", "检测", "电流声", "网罩", "电池",
    "会员", "优惠券", "价格保护", "发票", "转人工", "人工客服", "保修期", "定制商品",
    "蓝牙编解码", "售后", "退款", "返现",
]


def extract_triples_rule(text: str, chunk_id: str = "") -> tuple[list[str], list[tuple[str, str, str]]]:
    """规则抽取：共现 + 句式模板。

    规则抽取的召回率低，但精确率高、零成本。
    生产做法：规则 + LLM 双通道，规则处理高频句式，LLM 补长尾。
    """
    ents = [t for t in DOMAIN_TERMS if t in text]
    triples: list[tuple[str, str, str]] = []

    # 模板 1："X 由 Y 承担" / "X 需支付 Y"
    for m in re.finditer(r"([\u4e00-\u9fff]{2,6})(?:由|需支付|需缴纳|需收取)([\u4e00-\u9fff]{2,6})", text):
        a, b = m.group(1), m.group(2)
        if a in DOMAIN_TERMS and b in DOMAIN_TERMS:
            triples.append((b, "适用于", a))

# 模板 2："X 可申请 Y"
    for m in re.finditer(r"([\u4e00-\u9fff]{2,6})可申请([\u4e00-\u9fff]{2,6})", text):
        # 只保留词典里认识的，避免"可申请无理"这种切坏的短语进图
        a, b = m.group(1), m.group(2)
        if a in DOMAIN_TERMS and b in DOMAIN_TERMS:
            triples.append((b, "可由", a))

    # 共现：同一块里出现的实体两两相连（最粗糙但最稳）
    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            triples.append((ents[i], "共现于", ents[j]))

    return ents, triples


def extract_triples_llm(llm: Any, text: str) -> list[dict[str, str]]:
    """模型抽取（需要 API）。schema 约束是关键。"""
    from pydantic import BaseModel, Field

    class Triple(BaseModel):
        src: str = Field(description="主体实体（名词短语，尽量用原文用词）")
        rel: str = Field(description="关系（动词短语，如 适用于/由…承担/需要/禁止）")
        dst: str = Field(description="客体实体")

    class Triples(BaseModel):
        items: list[Triple]

    prompt = f"""从下面文本中抽取实体关系三元组。

要求：
1. 实体用原文中的名词短语，不要改写
2. 关系用简洁的动词短语
3. 只抽文本中**明确表达**的关系，不要推测
4. 最多抽 10 条

文本：
{text}"""
    out: Triples = llm.with_structured_output(Triples).invoke(prompt)
    return [t.model_dump() for t in out.items]


# ============================================================ 图增强检索

@dataclass
class GraphRetriever:
    """把向量检索和图扩展结合起来。

    流程：
      1. 向量检索拿到 top-k chunk（种子）
      2. 从 chunk 里的实体出发，图扩展 2 跳
      3. 收集扩展到的实体所在的 chunk
      4. 合并、去重、按距离排序
    """

    index: Any  # common.retrieval.Index
    graph: KnowledgeGraph
    chunk_entities: dict[str, list[str]] = field(default_factory=dict)

    def search(self, query: str, k: int = 5, hops: int = 2, seed_k: int = 3) -> list[tuple[str, float, str]]:
        seeds = self.index.search(query, k=seed_k)
        seed_chunks = [c.id for c, _ in seeds]

        # 种子 chunk 里的实体
        seed_ents: set[str] = set()
        for cid in seed_chunks:
            seed_ents.update(self.chunk_entities.get(cid, []))

        dist = self.graph.expand(seed_ents, hops=hops)

        # 按距离收集 chunk
        scored: dict[str, float] = {}
        for cid in seed_chunks:
            scored[cid] = 1.0

        for ent, d in dist.items():
            for cid in self.graph.entities[ent].chunk_ids:
                how = "graph" if cid not in scored else "seed"
                scored[cid] = max(scored.get(cid, 0.0), 1.0 / (1 + d))
                del how

        ordered = sorted(scored.items(), key=lambda x: -x[1])[:k]
        out = []
        for cid, s in ordered:
            reason = "向量命中" if cid in seed_chunks else "图扩展"
            out.append((cid, s, reason))
        return out


# ============================================================ 社区摘要

def summarize_community(llm: Any, members: set[str], relations: list[Relation]) -> str:
    """把一个社区压成一段摘要。

    这是 GraphRAG 回答"全局问题"的关键：
    用户问"这款产品主要有哪些问题"，
    没有任何一个片段能回答——但社区摘要可以。
    """
    rel_text = "\n".join(f"- {r.src} --{r.rel}--> {r.dst}" for r in relations[:40])
    prompt = f"""下面是知识图谱中一个主题社区的实体关系。请用 3 句话总结这个主题。

实体：{', '.join(sorted(members)[:30])}

关系：
{rel_text}

总结（不要罗列，要归纳）："""
    return llm.invoke(prompt).content
