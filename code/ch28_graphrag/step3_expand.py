"""第 28 章 · 第 3 级：沿图扩展检索 —— 用"距离"补向量的短板。

运行：
    python code/ch28_graphrag/step3_expand.py

新增的一个概念：**图增强检索（graph-augmented retrieval）**。

流程：
  ① 向量召回 top-k 作为"种子块"
  ② 种子块里的实体作为"种子实体"
  ③ 从种子实体出发做 BFS（默认 2 跳）
  ④ 按"距离越远、权重越低"给块打分

关键那句：`score = 1.0 / (1 + d)`
  它保证「图扩展」不会压过「向量直接命中」——
  种子永远是 1.0，2 跳的邻居最多 0.33。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"

DOMAIN_TERMS = (
    "无理由退货", "质量问题", "换新", "保修期", "运费", "检测费", "检测",
    "电流声", "网罩", "电池", "蓝牙编解码", "发票", "会员", "优惠券",
    "价保", "售后", "转人工", "备用机",
)


# ---------------------------------------------------------------- 基础设施

def hash_embed(text: str, dim: int = 256, unit: str = "word") -> list[float]:
    """字哈希向量。unit="char" 时退化成极弱的字面匹配（本章用来模拟向量失效）。"""
    vec = [0.0] * dim
    if unit == "char":
        tokens: list[str] = list(text)
    else:
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def split_by_heading(text: str, max_chars: int = 200) -> list[str]:
    out = []
    for p in re.split(r"\n(?=#{2,3} )", text):
        p = p.strip()
        if p:
            out.append(p[:max_chars])
    return out


@dataclass
class Graph:
    adj: dict[str, set[str]] = field(default_factory=lambda: {})
    ent_chunks: dict[str, set[str]] = field(default_factory=lambda: {})
    edges: list[tuple[str, str, str]] = field(default_factory=list)

    def link(self, a: str, b: str, rel: str = "同块出现") -> None:
        self.adj.setdefault(a, set()).add(b)
        self.adj.setdefault(b, set()).add(a)
        self.edges.append((a, rel, b))

    def expand(self, seeds: set[str], hops: int = 2) -> dict[str, int]:
        dist: dict[str, int] = {}
        q: deque[tuple[str, int]] = deque()
        for s in seeds:
            if s in self.adj:
                dist[s] = 0
                q.append((s, 0))
        while q:
            cur, d = q.popleft()
            if d >= hops:
                continue
            for nxt in self.adj.get(cur, ()):
                if nxt not in dist:
                    dist[nxt] = d + 1
                    q.append((nxt, d + 1))
        return dist

    def path(self, a: str, b: str, max_hops: int = 4) -> list[str] | None:
        """BFS 找最短路径，用来解释「为什么这两个概念相关」。"""
        if a not in self.adj or b not in self.adj:
            return None
        prev: dict[str, str | None] = {a: None}
        q: deque[tuple[str, int]] = deque([(a, 0)])
        while q:
            cur, d = q.popleft()
            if cur == b:
                out, node = [], cur
                while node is not None:
                    out.append(node)
                    node = prev[node]
                return list(reversed(out))
            if d >= max_hops:
                continue
            for nxt in self.adj.get(cur, ()):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append((nxt, d + 1))
        return None


def build_graph(chunks: list[str]) -> Graph:
    g = Graph()
    for n, c in enumerate(chunks):
        ents = [t for t in DOMAIN_TERMS if t in c]
        for e in ents:
            g.ent_chunks.setdefault(e, set()).add(n)
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                g.link(ents[i], ents[j])
    return g


# ---------------------------------------------------------------- 两种检索

@dataclass
class Retriever:
    chunks: list[str]
    graph: Graph
    hops: int = 2

    def __post_init__(self) -> None:
        self.vecs = [hash_embed(c) for c in self.chunks]

    def dense(self, q: str, k: int = 3) -> list[tuple[float, int]]:
        qv = hash_embed(q)
        return sorted(((cosine(qv, v), i) for i, v in enumerate(self.vecs)), reverse=True)[:k]

    def graph_augmented(self, q: str, k: int = 3, seed_k: int = 3) -> list[tuple[float, int, str]]:
        seeds = self.dense(q, k=seed_k)
        seed_chunks = [i for _, i in seeds]

        seed_ents = {e for e in DOMAIN_TERMS if any(e in self.chunks[i] for i in seed_chunks)}
        dist = self.graph.expand(seed_ents, hops=self.hops)

        scored: dict[int, tuple[float, str]] = {i: (1.0, "向量命中") for i in seed_chunks}
        for ent, d in dist.items():
            if d == 0:
                continue
            w = 1.0 / (1 + d)
            for cid in self.graph.ent_chunks.get(ent, ()):
                if cid not in scored or scored[cid][0] <= w:
                    # 多跳命中也给 1.0 会淹没向量排序，这里封顶到 0.9
                    scored[cid] = (min(w, 0.9), f"{d} 跳: {ent}")
        return sorted(((s, i, why) for i, (s, why) in scored.items()), reverse=True)[:k]

    def graph_first(self, q: str, k: int = 3, seed_k: int = 1) -> list[tuple[float, int, str]]:
        """只用 k 个种子 —— 模拟「向量只找到了一半」的真实情况。"""
        return self.graph_augmented(q, k=k, seed_k=seed_k)


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)
    g = build_graph(chunks)
    r = Retriever(chunks, g, hops=2)

    print("=" * 82)
    print("第 3 级：图扩展检索")
    print("=" * 82)
    print(f"  块 {len(chunks)}  实体 {len(g.ent_chunks)}  边 {len(g.edges)//2}  扩展 {r.hops} 跳")

    q = "会员退货时之前用掉的优惠券还能拿回来吗？"
    print(f"\n问题：{q}")
    print("\n  纯向量 top-3：")
    for s, i in r.dense(q, 3):
        print(f"    {s:.2f}  {chunks[i].split(chr(10))[0][:48]}")

    print("\n  图扩展 top-3（只用 1 个种子块，模拟「向量只找到一半」）：")
    for s, i, why in r.graph_first(q, 3):
        print(f"    {s:.2f}  {chunks[i].split(chr(10))[0][:40]:<42} ({why})")

    print("\n  解释：")
    print("    向量优先召回 3 条（4.1 会员权益 / 第四章标题 / 1.1 无理由退货），")
    print("    但真正能回答问题的只有 4.1。图扩展从「会员 / 优惠券」出发，")
    print("    把 4.1 稳定地钉在第一位 —— 即使向量排序抖动，它也不会掉出去。")
    print()
    print("  ⚠️ 诚实说：本例里向量本来就召回了 4.1，所以图扩展的**增量**看不出来。")
    print("     这是 GraphRAG 在小语料上最尴尬的地方 —— **它几乎没有优势**。")
    print("     它的价值要在「上千条政策 + 大量多跳/聚合问题」时才会显现。")
    print("     （本章 28.6 节的完整 demo 里，社区摘要才是聚合问题的正解）")

    print("\n" + "=" * 82)
    print("什么时候该上 GraphRAG：一个可操作的判据")
    print("=" * 82)
    print("  先做 3 件事（都很便宜）：")
    print("    1. 采样 50 条真实问题，人工标注每条需要几个块才能回答")
    print("    2. 统计「需要 ≥2 块且有依赖关系」的占比")
    print("    3. 看这部分的错误率")
    print()
    print("  判据：")
    print("    · 多跳+聚合问题 < 10% → **别上 GraphRAG**，先做第 30 章的混合检索")
    print("    · 10%~30% → 可以先做「父子分块 + 查询改写」，通常够用")
    print("    · > 30% 且错误率高 → GraphRAG 值得试，但要先算清 5~20 倍成本")

    print("\n" + "=" * 82)
    print("图还能回答「为什么这两个概念相关」")
    print("=" * 82)
    for a, b in (("运费", "质量问题"), ("电流声", "换新"), ("优惠券", "发票")):
        p = g.path(a, b)
        print(f"  {a} → {b}: {' → '.join(p) if p else '无路径（文档里没有直接关联）'}")

    print("\n" + "=" * 82)
    print("三个必须知道的代价")
    print("=" * 82)
    print("  1. 构建成本高：抽取 + 聚类 + 摘要，成本是普通 RAG 的 5~20 倍")
    print("  2. 噪声传播：共现边是噪声源，2 跳后可能扩散到无关实体")
    print("     → 所以生产上需要「边权重」或「关系类型过滤」，不能全用共现")
    print("  3. 更新困难：文档改了，图要重建（第 40 章会讲增量）")
    print()
    print("  👉 判据：**只有当「多跳 + 聚合」类问题占比高时，GraphRAG 才值得上。**")
    print("     否则先做第 30 章的混合检索 + 重排，能解决 80% 的问题。")


if __name__ == "__main__":
    main()
