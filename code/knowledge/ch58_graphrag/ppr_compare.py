"""同一多跳问题：向量 Top-k 的证据 vs PPR 的证据。"""

from __future__ import annotations

from graph_core import DOCS, build, ppr, query_entities, top_chunks, vector_topk


def main() -> None:
    query = "云海集团的 CEO 担任董事的蓝湖资本，投资了哪家供应商，它供应什么？"
    print("query:", query)
    print("query_entities:", query_entities(query))

    print("\n--- 向量 Top-2 ---")
    for node, score in vector_topk(query, k=2):
        print(f"{node}  score={score:.2f}  {DOCS[int(node[1:]) - 1]}")
    print("answer: 无法确定，缺少“蓝湖资本投资了谁”这一跳")

    graph, _ = build()
    rank = ppr(graph, query_entities(query))
    print("\n--- PPR Top-8 ---")
    for node, score in top_chunks(rank, k=8):
        print(f"{node}  score={score:.4f}  {DOCS[int(node[1:]) - 1]}")
    print("answer: 工业传感器（蓝湖资本 -> 星河科技 -> 工业传感器）")


if __name__ == "__main__":
    main()
