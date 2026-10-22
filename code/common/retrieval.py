"""第 11~12 章产出：一个不依赖外部服务的检索底座。

设计原则：
  · 嵌入可以用"真模型"，也可以用内置的确定性哈希嵌入（离线可跑）
  · 向量库用 numpy 暴力检索，够教学、零依赖、结果可复现
  · BM25 手写实现，让你看清"稀疏检索"到底在算什么

为什么不用 Qdrant/Milvus？
因为你要先理解"检索在做什么"，再谈"用哪个库"。
换库只改 Index.search 这一个函数。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np


# ============================================================ 嵌入

def hash_embed(text: str, dim: int = 256) -> np.ndarray:
    """确定性哈希嵌入（离线可用）。

    它不是好嵌入，但它有两个不可替代的优点：
      1. 不花钱、不需要网络
      2. 完全确定 —— 实验可复现，你才能判断"差异是策略导致的"

    ⚠️ 真实场景请换成 embedding 模型（见 class Embedder）。
    """
    v = np.zeros(dim, dtype=np.float32)
    # 用字符 bigram，对中文更友好
    tokens = [text[i : i + 2] for i in range(len(text) - 1)] or [text]
    for t in tokens:
        h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        v[idx] += sign
    n = np.linalg.norm(v)
    return v / n if n else v


class Embedder:
    """真嵌入模型（需要 API）。

    用 OpenAI 兼容的 /embeddings 接口，各家基本都支持。
    """

    def __init__(self, model: str = "text-embedding-v3") -> None:
        from openai import OpenAI

        from common.settings import get_settings

        s = get_settings()
        self.model = model
        self.client = OpenAI(api_key=s.api_key, base_url=s.base_url)
        self._cache: dict[str, np.ndarray] = {}

    def __call__(self, text: str) -> np.ndarray:
        if text in self._cache:
            return self._cache[text]
        r = self.client.embeddings.create(model=self.model, input=[text])
        v = np.array(r.data[0].embedding, dtype=np.float32)
        v /= np.linalg.norm(v) or 1
        self._cache[text] = v
        return v


# ============================================================ 分块

@dataclass
class Chunk:
    id: str
    text: str
    meta: dict = field(default_factory=dict)
    vector: np.ndarray | None = None


def split_fixed(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """定长切分。最简单，也最容易切断语义。"""
    if size <= 0:
        raise ValueError("size 必须为正")
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def split_by_heading(text: str, max_chars: int = 800) -> list[str]:
    """按标题切分（Markdown 场景最有效）。

    为什么按标题切？因为标题天然是"主题边界"，
    切出来的块语义完整度远高于定长切分。

    被切开的长节会保留标题前缀（`【标题】`），
    这样块的向量才带上"这一块是关于什么的"——即 contextual chunk header。
    """
    parts = re.split(r"\n(?=#{1,6} )", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            out.append(p)
        else:
            head = p.split("\n", 1)[0].lstrip("# ").strip()
            for sub in split_fixed(p, max_chars, overlap=80):
                out.append(sub if sub.startswith("#") else f"【{head}】\n{sub}")
    return out


def split_by_tokens(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    """按 token 数切分（生产环境唯一安全的做法）。

    为什么不能按字符切？第 2 章讲过：中文 1 字 ≈ 0.7 token，
    英文 4 字符 ≈ 1 token。按字符切会让中文块**悄悄超出嵌入模型上限**，
    被服务端静默截断——向量只覆盖了前半段，而你不报错、不知道。

    这里用估算（汉字 0.7 + 其余 1/4），是本书全书统一的公式。
    真要精确，用厂商的 tokenizer（第 2 章 step4 校准出的系数）。
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须为正")

    def est(s: str) -> float:
        cn = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
        return cn * 0.7 + (len(s) - cn) / 4

    out: list[str] = []
    buf = ""
    for ch in text:
        if est(buf + ch) > max_tokens:
            out.append(buf)
            # 回退 overlap 个字符，保证边界信息不丢
            buf = buf[-overlap_tokens:] + ch if overlap_tokens else ch
        else:
            buf += ch
    if buf.strip():
        out.append(buf)
    return [c for c in out if c.strip()]


def add_chunk_header(chunk: str, header: str) -> str:
    """给块加主题前缀（contextual chunk header）。

    「签收后 7 天内可以退」这句话本身没说是关于什么的。
    加上 `【一、无理由退货】` 之后，嵌入向量才带上主题信息。

    成本为零，效果通常明显 —— 尤其是条款句式高度相似的文档。
    """
    return f"【{header}】\n{chunk}"


def split_semantic(text: str, max_chars: int = 600, similarity_threshold: float = 0.35) -> list[str]:
    """伪语义切分：按句子相似度断点切。

    真正的语义切分要算句子嵌入，这里用"相邻句子词重叠率"近似，
    目的是让你看清"按语义断点切"的思路，且离线可复现。
    """
    sentences = [s for s in re.split(r"(?<=[。！？；\n])", text) if s.strip()]
    if not sentences:
        return []

    def overlap(a: str, b: str) -> float:
        ta = set(re.findall(r"[\u4e00-\u9fff]{2}|\w+", a))
        tb = set(re.findall(r"[\u4e00-\u9fff]{2}|\w+", b))
        if not ta or not tb:
            return 1.0
        return len(ta & tb) / len(ta | tb)

    chunks, cur = [], ""
    cnt = 0
    for i, s in enumerate(sentences):
        if cur and (cnt >= 1 and overlap(sentences[i - 1], s) < similarity_threshold or len(cur) + len(s) > max_chars):
            chunks.append(cur.strip())
            cur, cnt = s, 1
        else:
            cur += s
            cnt += 1
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def split_parent_child(text: str, parent_size: int = 1600, child_size: int = 400) -> list[tuple[str, str]]:
    """父子分块：小块用于检索（精确），大块用于喂给模型（完整）。

    这是生产 RAG 里最常用的技巧之一：
      · 检索用 child（短，语义聚焦，命中率高）
      · 命中后返回 parent（长，上下文完整，模型能读懂）

    返回 [(child, parent), ...]
    """
    pairs: list[tuple[str, str]] = []
    for parent in split_fixed(text, parent_size, overlap=100):
        for child in split_fixed(parent, child_size, overlap=50):
            pairs.append((child, parent))
    return pairs


# ============================================================ BM25

class BM25:
    """手写 BM25。

    公式（Okapi BM25）：
      score(q,d) = Σ IDF(t) * (tf * (k1+1)) / (tf + k1*(1 - b + b*|d|/avgdl))

    你只需要记住两件事：
      1. 词频（tf）越高越相关，但有饱和（不会无限涨）
      2. 文档越短越占优（长文档里的词被稀释）
    """

    def __init__(self, corpus: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [self._tokenize(d) for d in corpus]
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df: Counter = Counter()
        for d in self.docs:
            for t in set(d):
                df[t] += 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # 中文用 bigram，英文用词
        cn = re.findall(r"[\u4e00-\u9fff]", text)
        bigrams = ["".join(cn[i : i + 2]) for i in range(len(cn) - 1)]
        words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        return bigrams + words

    def scores(self, query: str) -> np.ndarray:
        q = self._tokenize(query)
        out = np.zeros(len(self.docs), dtype=np.float32)
        for i, d in enumerate(self.docs):
            tf = Counter(d)
            dl = len(d)
            s = 0.0
            for t in q:
                if t not in self.idf or t not in tf:
                    continue
                f = tf[t]
                s += self.idf[t] * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out[i] = s
        return out


# ============================================================ 索引

class Index:
    """极简向量索引（暴力检索）。

    换成 Qdrant 只需要改 search()：把 numpy 点积换成 client.search()。
    """

    def __init__(self, embed: Callable[[str], np.ndarray] = hash_embed) -> None:
        self.embed = embed
        self.chunks: list[Chunk] = []
        self._mat: np.ndarray | None = None

    def add(self, texts: Sequence[str], metas: Sequence[dict] | None = None) -> None:
        metas = metas or [{} for _ in texts]
        for i, (t, m) in enumerate(zip(texts, metas)):
            self.chunks.append(
                Chunk(id=f"c{len(self.chunks)}", text=t, meta=m, vector=self.embed(t))
            )
        self._mat = None  # 失效缓存

    def _matrix(self) -> np.ndarray:
        if self._mat is None:
            self._mat = np.vstack([c.vector for c in self.chunks]) if self.chunks else np.zeros((0, 1))
        return self._mat

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q = self.embed(query)
        sims = self._matrix() @ q
        idx = np.argsort(-sims)[:k]
        return [(self.chunks[i], float(sims[i])) for i in idx]

    def all_texts(self) -> list[str]:
        return [c.text for c in self.chunks]
