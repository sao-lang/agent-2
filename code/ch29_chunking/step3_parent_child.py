"""第 29 章 · 第 3 级：父子分块 —— 用小块检索，用大块回答。

运行：
    python code/ch29_chunking/step3_parent_child.py

新增的一个概念：**父子分块（parent-child chunking）**。

矛盾在哪里？
  · 块小 → 语义聚焦，命中率高（但上下文不够，模型答不全）
  · 块大 → 上下文完整（但主题被稀释，命中率低）

父子分块的解法：**检索用 child，生成用 parent。**

这一级用离线哈希嵌入跑真检索，比较三种策略的 recall@1 / recall@3，
并演示"命中 child 之后，返回给模型的是 parent"。
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"

QUESTIONS = [
    ("激活过的耳机能退吗？", "已激活的数码产品不适用无理由退货"),
    ("戴尔笔记本维修要多久？", None),          # 文档里没有，用来测"不该命中"
    ("右耳有电流声怎么办？", "蓝牙编解码"),
    ("退货运费谁出？", "运费由商家承担"),
    ("发票多久能开出来？", "发票"),
]


# ---------------------------------------------------------------- 离线嵌入

def hash_embed(text: str, dim: int = 256) -> list[float]:
    """确定性哈希嵌入：不需要 API，结果可复现。

    质量远不如真嵌入模型，但足以比较"分块策略"的相对优劣 ——
    因为所有策略用的是同一个嵌入函数。
    """
    vec = [0.0] * dim
    for token in re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower()):
        h = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------- 三种分块

def split_fixed(text: str, size: int, overlap: int = 0) -> list[str]:
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def split_by_heading(text: str, max_chars: int = 200) -> list[str]:
    """按标题切；超长的节再按长度切（保留标题前缀，让块带上主题）。"""
    parts = re.split(r"\n(?=#{2,3} )", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            out.append(p)
            continue
        head = p.split("\n", 1)[0].lstrip("# ").strip()
        for sub in split_fixed(p, max_chars, overlap=0):
            out.append(sub if sub.startswith("#") else f"【{head}】\n{sub}")
    return out


def split_parent_child(text: str, parent_chars: int = 200, child_chars: int = 50) -> list[tuple[str, str]]:
    """返回 [(child, parent), ...]。

    parent 用**标题切分**（保证一节一段话完整），child 在 parent 内部定长切。
    检索用 child，喂模型用 parent。
    """
    pairs = []
    for p in split_by_heading(text, max_chars=parent_chars):
        for c in split_fixed(p, child_chars, overlap=10):
            pairs.append((c, p))
    return pairs


@dataclass
class Index:
    vectors: list[list[float]]
    payloads: list[str]

    @classmethod
    def build(cls, chunks: list[str]) -> Index:
        return cls([hash_embed(c) for c in chunks], chunks)

    def search(self, query: str, k: int = 3) -> list[tuple[float, int]]:
        q = hash_embed(query)
        scored = [(cosine(q, v), i) for i, v in enumerate(self.vectors)]
        scored.sort(reverse=True)
        return scored[:k]


def hit(chunks: list[str], query: str, answer_key: str, k: int) -> bool:
    idx = Index.build(chunks)
    return any(answer_key in chunks[i] for _, i in idx.search(query, k))


# ---------------------------------------------------------------- 主程序

def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    # 只保留「小节正文」参与对比，去掉纯标题块（它们不含答案，会稀释指标）
    raw_chunks = split_by_heading(text, max_chars=200)
    sections = [c for c in raw_chunks if len(c.strip()) >= 30 and not c.strip().startswith("# ")]

    tiny = split_fixed("\n".join(sections), 50, overlap=0)
    big = split_by_heading(text, max_chars=200)
    pairs = split_parent_child(text, 200, 50)
    children = [c for c, _ in pairs]

    labeled = [(q, key) for q, key in QUESTIONS if key]

    print("=" * 78)
    print("第 3 级：小块 vs 大块 vs 父子分块")
    print("=" * 78)
    print(f"  评测问题 {len(labeled)} 个（另有 1 个「文档里没有」的问题用来测误召回）")
    print("  说明：把所有策略换成同一批「有内容的块」，避免标题块稀释指标")

    print(f"\n{'策略':<24}{'块数':>6}{'recall@1':>10}{'recall@3':>10}   命中失败的问题")
    print("-" * 78)
    for name, chunks in (
        ("小块 (50 字)", tiny),
        ("大块 (小节级, 最多200)", big),
        ("父子 (child 50)", children),
    ):
        r1 = sum(hit(chunks, q, k, 1) for q, k in labeled) / len(labeled)
        r3 = sum(hit(chunks, q, k, 3) for q, k in labeled) / len(labeled)
        misses = [q for q, k in labeled if not hit(chunks, q, k, 3)]
        print(f"{name:<24}{len(chunks):>6}{r1:>10.0%}{r3:>10.0%}   {', '.join(misses) or '—'}")

    print("\n" + "=" * 78)
    print("父子分块的关键：命中 child，返回 parent")
    print("=" * 78)
    q = "退货运费谁出？"
    idx = Index.build(children)
    score, i = idx.search(q, k=1)[0]
    child, parent = pairs[i]
    print(f"  问题：{q}")
    print(f"  命中 child（{len(child)} 字，score={score:.3f}）：")
    print(f"    {child.strip()[:64]}")
    print(f"\n  返回给模型的 parent（{len(parent)} 字）：")
    for line in parent.strip().split("\n")[:4]:
        print(f"    {line[:70]}")
    print()
    print("  👉 child 负责「找得准」，parent 负责「答得全」。")
    print("     这是唯一能同时提高召回精度和答案完整性的分块方式。")

    print("\n" + "=" * 78)
    print("三个必须知道的代价")
    print("=" * 78)
    print("  1. 存储翻倍：child 和 parent 都要存（child 存向量，parent 存原文）")
    print("  2. 去重：多个 child 命中同一个 parent 时，只能返回一份 parent")
    print("  3. 顺序：返回 parent 时要按原文档顺序拼接，否则模型读到的内容会跳来跳去")


if __name__ == "__main__":
    main()
