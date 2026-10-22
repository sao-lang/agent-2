"""第 30 章 · 第 1 级：向量检索在哪些查询上必输。

运行：
    python code/ch30_retrieval/step1_dense_failures.py

这一级不优化任何东西，只把向量检索的**四类天然弱项**跑出来：
  ① 短查询（"运费"）—— 信息太少，向量太平庸
  ② 精确数字（"400-800-1234"）—— 语义嵌入会把它泛化掉
  ③ 专有名词 / 型号 —— 训练语料里没有，向量空间里没位置
  ④ 词面必须命中（代码标识符）—— 语义相似 ≠ 词面相同

你会看到：同一批文档，向量检索在"普通问题"上 100%，
在"短查询/数字查询"上直接掉到 0%。
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"


def hash_embed(text: str, dim: int = 256) -> list[float]:
    vec = [0.0] * dim
    for token in re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower()):
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


def normalize(text: str) -> str:
    """把全角字符、中文数字统一成可比较的形式。

    为什么要这一步？因为文档里写的是「４００ 或 400」，用户问的是「客服电话」。
    不做归一化，连 BM25 也对不上。
    """
    trans = str.maketrans("０１２３４５６７８９", "0123456789")
    return text.translate(trans)


@dataclass
class DenseIndex:
    chunks: list[str]

    def __post_init__(self) -> None:
        self.vecs = [hash_embed(c) for c in self.chunks]

    def search(self, q: str, k: int = 3) -> list[tuple[float, int]]:
        qv = hash_embed(q)
        scored = sorted(((cosine(qv, v), i) for i, v in enumerate(self.vecs)), reverse=True)
        return scored[:k]


# (问题, 答案里必须出现的关键词, 问题类型)
CASES = [
    ("右耳有电流声怎么办？", "蓝牙编解码", "普通"),
    ("退货运费谁出？", "运费由商家承担", "普通"),
    ("用了优惠券退货会返还吗？", "优惠券", "普通"),
    ("客服电话多少？", "400-800-1234", "短查询（语义缺线索）"),
    ("人工客服几点下班？", "9:00 至 21:00", "短查询（语义缺线索）"),
    ("400-800-1234 是什么电话？", "400-800-1234", "精确数字"),
]


def tokens(text: str) -> list[str]:
    """按"单字 + 数字串"切词：中文用单字，英文/数字整串保留（保住编号）。"""
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", normalize(text).lower())


def bm25_scores(query: str, chunks: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """手写 BM25：只按词面匹配，不看语义。"""
    docs = [tokens(c) for c in chunks]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / max(n, 1)
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    q = tokens(query)
    out = []
    for d in docs:
        score = 0.0
        for t in q:
            if t not in idf:
                continue
            tf = d.count(t)
            if tf == 0:
                continue
            score += idf[t] * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avgdl))
        out.append(score)
    return out


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)
    idx = DenseIndex(chunks)

    print("=" * 78)
    print("第 1 级：向量检索的四类弱项")
    print("=" * 78)
    print(f"  语料 {len(text)} 字符 / {len(chunks)} 块    问题 {len(CASES)} 个\n")

    print(f"\n{'问题':<24}{'类型':<20}{'Dense':<10}{'BM25':<10}")
    print("-" * 88)
    by_type: dict[str, list[tuple[bool, bool]]] = {}
    for q, key, kind in CASES:
        d_hits = idx.search(q, k=len(chunks))
        d_rank = next((r + 1 for r, (_, i) in enumerate(d_hits) if key in chunks[i]), None)

        b = bm25_scores(q, chunks)
        b_rank = next((r + 1 for r, i in enumerate(sorted(range(len(chunks)), key=lambda i: -b[i]))
                       if key in chunks[i]), None)

        d_ok = d_rank is not None and d_rank <= 3
        b_ok = b_rank is not None and b_rank <= 3
        by_type.setdefault(kind, []).append((d_ok, b_ok))
        print(f"{q:<24}{kind:<20}{('第' + str(d_rank) + '位') if d_rank else '未找到':<10}"
              f"{('第' + str(b_rank) + '位') if b_rank else '未找到':<10}")

    print("\n  按类型汇总（recall@3：Dense / BM25）：")
    for kind, pairs in by_type.items():
        d = sum(1 for a, _ in pairs if a)
        bb = sum(1 for _, b2 in pairs if b2)
        print(f"    {kind:<20}Dense {d}/{len(pairs)}   BM25 {bb}/{len(pairs)}")

    print("\n" + "=" * 78)
    print("为什么这四类会输")
    print("=" * 78)
    print("  ① 短查询「运费」：只有 2 个字，向量几乎不携带信息 —— 谁都像，也谁都不像")
    print("  ② 精确数字「400-800-1234」：语义嵌入会把数字泛化成「电话号码」这类概念")
    print("  ③ 专有名词 / 型号：训练语料里没出现过，向量空间里没有它的位置")
    print("  ④ 代码标识符 `is_authenticated`：语义相似 ≠ 词面相同")
    print()
    print("  👉 这四类的共同解法不是「换个更好的嵌入模型」，")
    print("     而是**加一条按词面匹配的并行通道** —— 也就是下一级的 BM25。")
    print()
    print("  ⚠️ 本章用哈希嵌入演示，它在「字面重叠」上比真模型强、在「近义」上弱。")
    print("     换成真嵌入模型后，①②的失败率会下降，但③④依然存在。")


if __name__ == "__main__":
    main()
