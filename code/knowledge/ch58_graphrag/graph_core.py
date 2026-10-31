"""GraphRAG 原理演示：规则抽取 + 二部图 + 手写 PPR。

真实系统把 extract() 换成 LLM 抽取；图存储换成图数据库；
PPR 换成图库实现。这里只用标准库，保证输出可复现。
"""

from __future__ import annotations

import re
from collections import defaultdict

DOCS = [
    "星河科技是云海集团的供应商。",
    "云海集团的 CEO 是张伟。",
    "张伟同时担任蓝湖资本的董事。",
    "蓝湖资本投资了星河科技。",
    "星河科技供应工业传感器。",
    "云海集团采购工业传感器。",
    "远山科技是云海集团的供应商。",
    "远山科技是蓝湖资本的客户。",
    "蓝湖资本关注新能源赛道。",
    "云海集团总部在杭州。",
    "星河科技总部在深圳。",
    "远山科技总部在苏州。",
]

ENTITIES = ["星河科技", "云海集团", "蓝湖资本", "远山科技", "张伟", "工业传感器"]


def extract(text: str) -> list[tuple[str, str, str]]:
    """规则替身：只抽固定句式。真实系统把这里换成 LLM 抽取。"""
    patterns = [
        (r"(.+?)是(.+?)的供应商", "供应商"),
        (r"(.+?)的 CEO 是(.+?)。", "CEO"),
        (r"(.+?)(?:同时)?担任(.+?)的董事", "董事"),
        (r"(.+?)投资了(.+?)。", "投资"),
        (r"(.+?)供应(?!商)(.+?)。", "供应"),
        (r"(.+?)是(.+?)的客户", "客户"),
    ]
    rows = []
    for pattern, relation in patterns:
        match = re.match(pattern, text)
        if match:
            rows.append((match.group(1).strip(), relation, match.group(2).strip()))
    return rows


def build():
    graph: dict[str, set[str]] = defaultdict(set)
    edge_rows: list[tuple[str, str, str, int]] = []
    for index, text in enumerate(DOCS):
        chunk = f"c{index + 1}"
        for entity in ENTITIES:
            if entity in text:
                graph[chunk].add(f"e:{entity}")
                graph[f"e:{entity}"].add(chunk)
        for left, relation, right in extract(text):
            edge_rows.append((left, relation, right, index + 1))
            graph[f"e:{left}"].add(f"e:{right}")
            graph[f"e:{right}"].add(f"e:{left}")
    return graph, edge_rows


def ppr(graph: dict[str, set[str]], seeds: list[str], restart: float = 0.15,
        iterations: int = 30) -> dict[str, float]:
    nodes = list(graph)
    if not nodes:
        return {}
    rank = {node: 1.0 / len(nodes) for node in nodes}
    seed_set = {f"e:{item}" for item in seeds}
    for _ in range(iterations):
        new = {node: 0.0 for node in nodes}
        for node in nodes:
            degree = len(graph[node])
            if degree == 0:
                continue
            share = rank[node] * (1.0 - restart) / degree
            for neighbor in graph[node]:
                new[neighbor] += share
        for node in nodes:
            if node in seed_set:
                new[node] += restart / max(1, len(seed_set))
        rank = new
    return rank


def top_chunks(rank: dict[str, float], k: int = 3) -> list[tuple[str, float]]:
    rows = [(node, score) for node, score in rank.items() if node.startswith("c")]
    rows.sort(key=lambda pair: pair[1], reverse=True)
    return rows[:k]


def bigrams(text: str) -> set[str]:
    clean = "".join(ch for ch in text if not ch.isspace())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def vector_topk(query: str, k: int = 2) -> list[tuple[str, float]]:
    q = bigrams(query)
    scored = []
    for index, text in enumerate(DOCS):
        d = bigrams(text)
        score = len(q & d) / max(1, len(q))
        if score:
            scored.append((f"c{index + 1}", score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]


def query_entities(query: str) -> list[str]:
    return [entity for entity in ENTITIES if entity in query]
