"""第 14 章示例：多跳问题，向量检索 vs 图检索（不需要 API）。

运行：
    python code/ch14_graphrag/demo_graphrag.py

三类问题的对照：
  A. 单跳（向量就够）
  B. 多跳（需要图扩展）
  C. 全局聚合（需要社区摘要）

这就是 GraphRAG 存在的三个理由。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.graph_rag import GraphRetriever, KnowledgeGraph, extract_triples_rule  # noqa: E402
from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402

DOC = (Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md").read_text(encoding="utf-8")


def build() -> tuple[Index, KnowledgeGraph, dict[str, list[str]], GraphRetriever]:
    idx = Index(embed=hash_embed)
    chunks = split_by_heading(DOC, max_chars=260)
    idx.add(chunks)

    g = KnowledgeGraph()
    chunk_entities: dict[str, list[str]] = {}
    for c in idx.chunks:
        ents, triples = extract_triples_rule(c.text, c.id)
        chunk_entities[c.id] = ents
        for e in ents:
            g.add_entity(e, chunk_id=c.id)
        for src, rel, dst in triples:
            g.add_relation(src, rel, dst, chunk_id=c.id)
            g.entities[src].chunk_ids.add(c.id)
            g.entities[dst].chunk_ids.add(c.id)

    return idx, g, chunk_entities, GraphRetriever(index=idx, graph=g, chunk_entities=chunk_entities)


def show(idx: Index, title: str, results) -> None:
    print(f"\n--- {title} ---")
    for item in results:
        if isinstance(item, tuple) and len(item) == 3:
            cid, score, reason = item
        else:
            cid, score = item
            reason = "向量"
        chunk = next(c for c in idx.chunks if c.id == cid)
        head = chunk.text.split("\n")[0][:30].replace("\n", " ")
        print(f"  [{reason:<4}] {score:.2f}  {head}：{chunk.text[len(head):len(head) + 44].strip()[:44]}")


def main() -> None:
    idx, g, chunk_entities, retriever = build()

    print(f"语料：{len(idx.chunks)} 块    实体：{len(g.entities)}    关系：{len(g.relations)}")
    print(f"实体样例：{', '.join(list(g.entities)[:12])}")

    print("\n" + "=" * 74)
    print("A. 单跳问题：向量检索就够了")
    print("=" * 74)
    q = "无理由退货几天内可以申请？"
    print(f"问题：{q}")
    show(idx, "纯向量 top-3", [(c.id, s) for c, s in idx.search(q, 3)])
    show(idx, "图扩展 top-3", retriever.search(q, k=3))

    print("\n" + "=" * 74)
    print("B. 多跳问题：向量检索会漏掉关键中间环节")
    print("=" * 74)
    q = "会员退货时之前用掉的优惠券还能拿回来吗？"
    print(f"问题：{q}")
    show(idx, "纯向量 top-3", [(c.id, s) for c, s in idx.search(q, 3)])
    show(idx, "图扩展 top-3", retriever.search(q, k=3, hops=2))

    print("\n  说明：")
    print("    这个问题的答案在「4.1 会员权益」——'会员退货时，已使用的优惠券不返还'")
    print("    但问题里出现了「退货」和「优惠券」，向量容易召回「1.1 无理由退货」和「会员」。")
    print("    图检索能从「优惠券」出发，经「会员」跳到正确的那一块。")

    print("\n" + "=" * 74)
    print("C. 全局问题：没有任何单一块能回答")
    print("=" * 74)
    q = "这个平台在售后方面主要有哪些规则？"
    print(f"问题：{q}")
    show(idx, "纯向量 top-3（都是零散片段）", [(c.id, s) for c, s in idx.search(q, 3)])

    print("\n  → 这类问题需要「社区摘要」：先把相关实体的关系聚成一个圈子，再总结。")
    comms = [c for c in g.communities() if len(c) >= 4]
    print(f"\n  检测到 {len(comms)} 个规模≥4 的社区（连通分量近似）：")
    for i, comp in enumerate(sorted(comms, key=len, reverse=True)[:4], 1):
        print(f"    社区 {i}（{len(comp)} 个实体）：{', '.join(sorted(comp)[:8])}...")

    print("\n" + "=" * 74)
    print("D. 解释能力：为什么这两个概念相关")
    print("=" * 74)
    pairs = [("优惠券", "退货"), ("运费", "质量问题"), ("电流声", "换新")]
    for a, b in pairs:
        ps = g.paths(a, b, max_len=3)
        if ps:
            print(f"  {a} → {b}：{' / '.join(' → '.join(p) for p in ps[:2])}")
        else:
            print(f"  {a} → {b}：无路径（说明这两个概念在文档里没有直接关联）")

    print("\n" + "=" * 74)
    print("⚠️ 这份报告的可信度")
    print("=" * 74)
    print("  · 抽取用的是规则（共现 + 模板），召回率低，只能作为教学演示")
    print("  · 社区用的是连通分量，不是 Leiden 层次聚类")
    print("  · 这份语料只有 889 字，图的规模太小，多跳优势不明显")
    print("  · 生产场景请用：LLM 抽取三元组 + Leiden 聚类 + 社区摘要")
    print("\n  👉 GraphRAG 的成本是普通 RAG 的 5-20 倍（抽取 + 聚类 + 摘要都要花钱），")
    print("     只在多跳/聚合问题占比高时才值得上。")


if __name__ == "__main__":
    main()
