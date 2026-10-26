"""第 30 章产出：检索优化的四件工具。

  1. 混合检索（向量 + BM25）与 RRF 融合
  2. 重排序（Rerank）—— 用一个"交叉编码器式"的打分器模拟
  3. 查询改写（HyDE / Multi-Query）
  4. 元数据过滤

全部可离线运行，指标可复现。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from common.retrieval import BM25, Index


# ============================================================ RRF 融合

def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion。

    score(d) = Σ 1 / (k + rank_i(d))

    为什么用 RRF 而不是分数加权？
    因为向量相似度（0~1）和 BM25 分数（0~30）**量纲完全不同**，
    直接相加是错的。RRF 只看排名，天然免疫量纲问题。

    k=60 是论文里的经验值：它让"第 1 名"和"第 2 名"的差距不至于过分悬殊。
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])


# ============================================================ Rerank

def lexical_rerank(query: str, docs: list[str]) -> list[float]:
    """模拟"交叉编码器"的打分：直接算 query 与 doc 的细粒度匹配。

    真实的 cross-encoder（如 BGE-Reranker）会同时看 query 和 doc，
    比"双塔向量"精度高得多——因为它能看到 token 级别的交互。

    这里用一个可解释的近似：query 的词覆盖率 + 顺序连续匹配加分。
    """
    def tokens(s: str) -> list[str]:
        cn = re.findall(r"[\u4e00-\u9fff]", s)
        grams = ["".join(cn[i : i + 2]) for i in range(len(cn) - 1)]
        return grams + re.findall(r"[a-zA-Z0-9_]+", s.lower())

    q = tokens(query)
    out = []
    for d in docs:
        dt = tokens(d)
        if not q:
            out.append(0.0)
            continue
        hit = sum(1 for t in q if t in dt) / len(q)
        # 连续命中加分（说明是"整句匹配"而不是"散落命中"）
        bonus = 0.0
        qset = list(dict.fromkeys(q))
        for n in range(len(qset), 1, -1):
            for i in range(len(qset) - n + 1):
                needle = "".join(qset[i : i + n])
                if needle and needle in d:
                    bonus = min(0.3, n * 0.05)
                    break
            if bonus:
                break
        out.append(hit + bonus)
    return out


# ============================================================ 查询改写

def multi_query_offline(query: str) -> list[str]:
    """离线版"多查询扩展"：用同义词表 + 模板生成 3 个变体。

    真实实现用模型（见 multi_query_llm）。
    为什么要扩展？因为用户说的话和文档里的说法常常不同：
      "耳机会响" → "电流声" / "杂音" / "滋滋声"
    """
    SYNONYMS = {
        "响": ["电流声", "杂音"],
        "退货": ["无理由退货", "退款"],
        "运费": ["邮费", "快递费"],
        "转人工": ["人工客服", "客服电话"],
        "多久": ["几天", "时效"],
    }
    variants = [query]
    for k, alts in SYNONYMS.items():
        if k in query:
            for a in alts:
                variants.append(query.replace(k, a))
    return list(dict.fromkeys(variants))[:4]


def hyde_offline(query: str) -> str:
    """假 HyDE：把问题改写成"一段像答案的话"。

    HyDE 的核心思想：**问题向量和答案向量在空间里不对齐**。
    与其拿问题去检索答案，不如先"编一个假答案"，用假答案去检索真答案。

    ⚠️ 代价：多一次模型调用，而且编造的假答案可能引入偏差。
    """
    return f"关于{query}，政策规定如下：" + query.replace("吗", "").replace("？", "。")


# ============================================================ 完整检索链

@dataclass
class RetrievalPipeline:
    """生产 RAG 的检索链骨架。

    dense  →  只看向量（基线）
    hybrid →  + BM25 + RRF
    rerank →  + 重排序（top-N 收窄到 top-K）
    full   →  + 查询改写（多查询 + RRF）
    """

    index: Index
    mode: str = "dense"
    bm25: BM25 | None = None
    fuse_k: int = 60
    rerank_candidates: int = 20

    def __post_init__(self) -> None:
        if self.bm25 is None:
            self.bm25 = BM25(self.index.all_texts())

    def _dense(self, q: str, n: int) -> list[str]:
        return [c.id for c, _ in self.index.search(q, k=n)]

    def _sparse(self, q: str, n: int) -> list[str]:
        assert self.bm25 is not None
        s = self.bm25.scores(q)
        order = np.argsort(-s)[:n]
        return [self.index.chunks[i].id for i in order]

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        by_id = {c.id: c for c in self.index.chunks}

        if self.mode == "dense":
            return [(c.id, s) for c, s in self.index.search(query, k=k)]

        if self.mode == "hybrid":
            dense = self._dense(query, self.rerank_candidates)
            sparse = self._sparse(query, self.rerank_candidates)
            fused = rrf_fuse([dense, sparse], k=self.fuse_k)[:k]
            return fused

        if self.mode == "rerank":
            dense = self._dense(query, self.rerank_candidates)
            docs = [by_id[i].text for i in dense]
            scores = lexical_rerank(query, docs)
            ranked = sorted(zip(dense, scores), key=lambda x: -x[1])[:k]
            return ranked

        if self.mode == "full":
            variants = multi_query_offline(query)
            rankings: list[list[str]] = []
            for v in variants:
                rankings.append(self._dense(v, self.rerank_candidates))
                rankings.append(self._sparse(v, self.rerank_candidates))
            fused = rrf_fuse(rankings, k=self.fuse_k)
            cand_ids = [i for i, _ in fused][: self.rerank_candidates]
            docs = [by_id[i].text for i in cand_ids]
            scores = lexical_rerank(query, docs)
            return sorted(zip(cand_ids, scores), key=lambda x: -x[1])[:k]

        raise ValueError(self.mode)
