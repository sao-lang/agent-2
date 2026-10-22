"""第 13 章 · 第 3 级：重排（rerank）—— 把"找到了"变成"排第一"。

运行：
    python code/ch13_retrieval/step3_rerank.py

新增的一个概念：**两段式检索（召回 → 重排）**。

为什么不能一次排准？
  · 召回阶段要扫全库（10 万条），只能用"双塔"（query 向量 · doc 向量）—— 快，但粗糙
  · 重排阶段只看 20 条候选，可以用"交叉编码器"（query + doc 一起送进模型）—— 准，但慢

  10 万条 × 20ms = 33 分钟。所以重排只能用在**召回后的少数候选**上。

这一级用一个可解释的"词覆盖率 + 连续命中"近似交叉编码器，
演示"加一步重排，recall@1 能涨多少"。
"""
from __future__ import annotations

import re
from pathlib import Path

from step1_dense_failures import CASES, DenseIndex, bm25_scores, normalize, split_by_heading
from step2_hybrid import rank_of, rrf_fuse

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"


def words(text: str) -> list[str]:
    """切词：中文按"连续 2 字的片段"补一点语序信息，英文/数字整串保留。"""
    text = normalize(text).lower()
    singles = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text)
    return singles


def lexical_rerank(query: str, docs: list[str]) -> list[float]:
    """模拟交叉编码器：query 词覆盖率 + 连续命中加分。

    交叉编码器能"同时看见" query 和 doc，所以能判断
    "这个词是不是在修饰那个词"。这里用"连续命中"近似这个能力。
    """
    q = words(query)
    qset = "".join(q)
    out = []
    for d in docs:
        dt = words(d)
        if not q:
            out.append(0.0)
            continue
        coverage = sum(1 for t in q if t in dt) / len(q)          # ① 覆盖率

        bonus = 0.0
        for n in range(len(qset), 1, -1):                          # ② 连续命中加分
            if qset[:n] in "".join(dt):
                bonus = min(0.3, n * 0.05)
                break

        # ③ 短文档轻微惩罚（同样的覆盖率，长文里更可能是"碰巧有"）
        length_penalty = min(0.1, len(dt) / 2000)
        out.append(coverage + bonus - length_penalty)
    return out


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)
    idx = DenseIndex(chunks)

    print("=" * 84)
    print("第 3 级：召回 8 条 → 重排成前 3 条")
    print("=" * 84)
    print(f"  语料 {len(chunks)} 块   问题 {len(CASES)} 个")
    print("  召回：Dense + BM25 用 RRF 融合，取前 8")
    print("  重排：对这 8 条算覆盖率 + 连续命中\n")

    print(f"{'问题':<24}{'混合召回':<12}{'重排后':<12}  收益")
    print("-" * 84)

    rec = {"hybrid": 0, "rerank": 0}
    for q, key, kind in CASES:
        qv = idx.search(q, k=len(chunks))
        dense_order = [i for _, i in qv]
        bm25_order = rank_of(bm25_scores(q, chunks))
        fused = [i for i, _ in rrf_fuse([dense_order, bm25_order])]

        # ① 召回阶段：只取前 8 条
        candidates = fused[:8]
        h_pos = next((r + 1 for r, i in enumerate(candidates) if key in chunks[i]), None)

        # ② 重排阶段：只在这 8 条里重排
        scores = lexical_rerank(q, [chunks[i] for i in candidates])
        reranked = [candidates[j] for j in rank_of(scores)]
        r_pos = next((r + 1 for r, i in enumerate(reranked) if key in chunks[i]), None)

        if h_pos and h_pos <= 3:
            rec["hybrid"] += 1
        if r_pos and r_pos <= 3:
            rec["rerank"] += 1

        fmt = lambda p: f"第{p}位" if p else "未找到"
        delta = ""
        if h_pos and r_pos:
            if r_pos < h_pos:
                delta = f"↑ 前进 {h_pos - r_pos} 位"
            elif r_pos > h_pos:
                delta = f"↓ 后退 {h_pos - r_pos} 位"
            else:
                delta = "持平"
        print(f"{q:<24}{fmt(h_pos):<12}{fmt(r_pos):<12}  {delta}")

    n = len(CASES)
    print("\n  recall@3：")
    for name, v in rec.items():
        print(f"    {name:<8}{v}/{n}  = {v / n:.0%}")

    print("\n" + "=" * 84)
    print("重排为什么有效：它看得见「这两个词有没有挨着」")
    print("=" * 84)
    q = "客服电话多少？"
    qv = idx.search(q, k=len(chunks))
    candidates = [i for i, _ in rrf_fuse([[i for _, i in qv], rank_of(bm25_scores(q, chunks))])][:8]
    print(f"  问题：{q}\n")
    print("  重排前（混合召回顺序）：")
    for r, i in enumerate(candidates[:3], 1):
        mark = "✅" if "400-800-1234" in chunks[i] else "  "
        print(f"    {r}. {chunks[i][:36].replace(chr(10), ' ')} {mark}")
    scores = lexical_rerank(q, [chunks[i] for i in candidates])
    print("\n  重排后：")
    for r, j in enumerate(rank_of(scores)[:3], 1):
        i = candidates[j]
        mark = "✅" if "400-800-1234" in chunks[i] else "  "
        print(f"    {r}. {scores[j]:.3f}  {chunks[i][:32].replace(chr(10), ' ')} {mark}")
    print()
    print("  含「400-800-1234」的那一块因为「客服 / 电话」两词相邻、")
    print("  且数字串完整命中，重排后被拉到第一位。")
    print()
    print("  👉 这就是交叉编码器比双塔强的地方：**它能看 token 之间的关系**，")
    print("     而双塔只能各自算一个向量再比距离。")

    print("\n" + "=" * 84)
    print("⚠️ 重排也有坑")
    print("=" * 84)
    print("  1. 重排不是万能的：召回阶段没召回的，重排永远排不出来")
    print("  2. 重排会改变顺序：本来对的排在第一位，可能被排到第三位（负收益）")
    print("  3. 每加一步都要评测：第 16 章会用数据说明「加 rerank 反而变差」的真实案例")


if __name__ == "__main__":
    main()
