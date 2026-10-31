"""12 篇文档 -> 实体/关系 -> 二部图。"""

from __future__ import annotations

from graph_core import DOCS, build


def main() -> None:
    graph, edges = build()
    chunks = [node for node in graph if node.startswith("c")]
    entities = [node for node in graph if node.startswith("e:")]
    edge_count = sum(len(neighbors) for neighbors in graph.values()) // 2
    print("docs:", len(DOCS))
    print("chunks:", len(chunks), "entities:", len(entities), "edges:", edge_count)
    print("extract_calls:", len(DOCS))
    print("relations:")
    for left, relation, right, doc in edges:
        print(f"  {left} -[{relation}]-> {right}  (c{doc})")


if __name__ == "__main__":
    main()
