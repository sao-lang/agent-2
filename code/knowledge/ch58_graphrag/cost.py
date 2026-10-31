"""普通 RAG 与 GraphRAG 的成本对照。"""

from __future__ import annotations


def main() -> None:
    docs = 12
    chunks = 12
    entities = 6
    edges = 27
    extract_calls = 12

    rag_index_tokens = 1_800
    rag_query_tokens = 320
    graph_extract_tokens = 14_400
    graph_store_edges = edges
    graph_query_tokens = 1_050

    index_multiple = (rag_index_tokens + graph_extract_tokens) / rag_index_tokens
    query_multiple = graph_query_tokens / rag_query_tokens
    total_multiple = (rag_index_tokens + graph_extract_tokens + graph_query_tokens) / (
        rag_index_tokens + rag_query_tokens
    )

    print("docs:", docs, "chunks:", chunks, "entities:", entities, "edges:", graph_store_edges)
    print("extract_calls:", extract_calls)
    print(f"普通 RAG  : index={rag_index_tokens} query={rag_query_tokens}")
    print(f"GraphRAG  : index={rag_index_tokens + graph_extract_tokens} "
          f"query={graph_query_tokens}")
    print(f"index 倍数: {index_multiple:.1f}x")
    print(f"query 倍数: {query_multiple:.1f}x")
    print(f"总倍数    : {total_multiple:.1f}x")
    print("构成：抽取 %.0f%%，图存储 %d 条边，查询迭代 30 次"
          % (graph_extract_tokens / (graph_extract_tokens + graph_query_tokens) * 100,
             graph_store_edges))


if __name__ == "__main__":
    main()
