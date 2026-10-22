"""第 15 章 · 第 1 级：什么时候向量检索"答得出但答不全"。

运行：
    python code/ch15_graphrag/step1_multihop.py

这一级不建图，只把三类问题摆出来，让你看清"多跳"和"聚合"到底难在哪。

  ① 单跳：答案集中在一块里  → 向量检索够用
  ② 多跳：答案需要 A→B→C    → 向量可能召回中间那一块，也可能不召
  ③ 聚合：答案是十个片段的共性 → **没有任何一块是答案**

关键分辨方法：看"答案在几个块里"。
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


@dataclass
class Index:
    chunks: list[str]

    def __post_init__(self) -> None:
        self.vecs = [hash_embed(c) for c in self.chunks]

    def search(self, q: str, k: int = 3) -> list[tuple[float, int]]:
        qv = hash_embed(q)
        return sorted(((cosine(qv, v), i) for i, v in enumerate(self.vecs)), reverse=True)[:k]


# (问题, 类型, 答案涉及的块数, 判断依据)
CASES = [
    ("无理由退货几天内可以申请？", "单跳", 1, "答案集中在 1.1 一块"),
    ("会员退货时优惠券能拿回来吗？", "多跳", 1, "要先找到 4.1「会员权益」，再读其中一句；问题词却指向 1.1「退货」"),
    ("这个平台售后主要有哪些规则？", "聚合", 6, "答案 = 退货/运费/发票/会员/检测/时效 六块的共性，没有单块能回答"),
]


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)
    idx = Index(chunks)

    print("=" * 80)
    print("第 1 级：三类问题的检索表现")
    print("=" * 80)
    print(f"  语料 {len(text)} 字符 / {len(chunks)} 块\n")

    for q, kind, n_blocks, why in CASES:
        print(f"【{kind}】{q}")
        print(f"  答案涉及 {n_blocks} 个块 —— {why}")
        print("  向量 top-3：")
        for score, i in idx.search(q, k=3):
            first = chunks[i].split("\n")[0][:46]
            print(f"    {score:.2f}  {first}")
        print()

    print("=" * 80)
    print("三类问题的关键差别（这张表要记住）")
    print("=" * 80)
    print("  ┌─────────┬──────────────┬──────────────────────────────┐")
    print("  │ 类型    │ 答案在哪     │ 向量检索为什么不够            │")
    print("  ├─────────┼──────────────┼──────────────────────────────┤")
    print("  │ 单跳    │ 1 块里       │ 够用                          │")
    print("  │ 多跳    │ A 块的条件   │ 只看「整体像不像」，不懂「谁引用谁」│")
    print("  │ 聚合    │ 10 块的共性  │ **没有一块是答案**             │")
    print("  └─────────┴──────────────┴──────────────────────────────┘")
    print()
    print("  👉 判断方法：**看答案需要几个块才能拼出来。**")
    print("     1 块 → 向量够了；多块有依赖关系 → 需要图；多块无依赖 → 需要摘要/聚类。")
    print()
    print("  ⚠️ 这份语料只有 889 字，三类问题的差距不明显。")
    print("     换成上千条政策后，「聚合」类问题会随着文档增长而彻底崩掉。")


if __name__ == "__main__":
    main()
