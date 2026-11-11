"""向量检索后端（SUPPLEMENT B1-fake / B3）：IndexBackend 协议的向量实现。

* `HashingEmbedder` —— 零依赖确定性嵌入（字符 n-gram 哈希到固定维向量）；
  它是"真 embedding 的 fake"，让嵌入→入库→检索全链路离线可测（R6 纪律）。
  生产嵌入（bge/openai text-embedding）按同样协议放 adapters/，走 extras。
* `InMemoryVectorIndex` —— 实现 IndexBackend 协议：余弦相似度、Namespace
  隔离、过滤下推（先筛后搜，SPEC M12.2）、top-k 返回 Recalled。

替换实验：`MemoryIndex`（二元组打分）↔ `InMemoryVectorIndex`（向量检索）
互换，下游行为一致，只有召回质量变化；真 Qdrant/pgvector 接入后同样通过
tests/conformance.py 的一致性基类。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Sequence

from harness.contracts.types import Document, Namespace, Recalled

_DIM = 256


class HashingEmbedder:
    """确定性哈希嵌入：字符 2-gram + 3-gram 哈希累加，L2 归一化。

    同文本永远同向量（可回放）；语义弱但排序特征够用——离线测试与
    conformance 基线的标准 fake。"""

    name = "hashing"

    def __init__(self, dim: int = _DIM) -> None:
        self.dim = dim

    def _bucket(self, gram: str) -> int:
        digest = hashlib.md5(gram.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % self.dim

    def embed(self, text: str) -> list[float]:
        clean = "".join(ch for ch in text.lower() if not ch.isspace())
        vec = [0.0] * self.dim
        for n in (2, 3):
            for i in range(max(0, len(clean) - n + 1)):
                vec[self._bucket(clean[i:i + n])] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, docs: Sequence[Document]) -> list[Document]:
        """给文档补 vector 字段（contracts Document.vector 此前无人写入）。"""
        return [Document(id=d.id, text=d.text, metadata=d.metadata,
                         vector=self.embed(d.text))
                for d in docs]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _match_filters(metadata: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    """过滤下推：先按 filters 筛，再算相似度（SPEC M12.2，防租户泄漏）。"""
    if not filters:
        return True
    return all(metadata.get(k) == v for k, v in filters.items())


class InMemoryVectorIndex:
    """IndexBackend 协议的内存向量实现（C3：跨 ns 读取视为不存在）。"""

    def __init__(self, embedder: Any = None) -> None:
        self.embedder = embedder or HashingEmbedder()
        self._rows: dict[tuple, list[Document]] = {}

    @staticmethod
    def _key(ns: Namespace) -> tuple:
        return ns.as_tuple()

    async def upsert(self, ns: Namespace, docs: Sequence[Document]) -> int:
        bucket = self._rows.setdefault(self._key(ns), [])
        with_vectors = self.embedder.embed_documents(docs)
        index = {d.id: i for i, d in enumerate(bucket)}
        for doc in with_vectors:
            if doc.id in index:
                bucket[index[doc.id]] = doc
            else:
                bucket.append(doc)
        return len(docs)

    async def search(self, ns: Namespace, query: Any, *, k: int,
                     filters: dict[str, Any] | None = None) -> list[Recalled]:
        rows = self._rows.get(self._key(ns), [])
        if filters:
            rows = [d for d in rows if _match_filters(d.metadata, filters)]
        qvec = query if isinstance(query, list) else self.embedder.embed(str(query))
        scored = []
        for doc in rows:
            dvec = doc.vector if doc.vector else self.embedder.embed(doc.text)
            score = _cosine(qvec, dvec)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [Recalled(text=d.text, score=round(score, 6),
                         source=str(d.metadata.get("source", d.id)),
                         layer="semantic")
                for score, d in scored[:k]]
