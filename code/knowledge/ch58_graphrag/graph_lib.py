"""规则替身抽取 + 二部图 + PPR。

真实项目把 extract() 换成 LLM 抽取即可，图与 PPR 不变。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from data import DOCS

SUPPLIER_RE = re.compile(r"(.+?)公司的供应商是(.+?)。")
CEO_RE = re.compile(r"(.+?)公司的 CEO 是(.+?)。")


def normalize(name: str) -> str:
    return name.replace("公司", "").strip()


@dataclass
class Triple:
    subject: str
    relation: str
    obj: str
    source: str


def extract() -> tuple[list[Triple], dict[str, set[str]]]:
    triples: list[Triple] = []
    mentions: dict[str, set[str]] = defaultdict(set)
    for doc_id, text in DOCS:
        for match in SUPPLIER_RE.finditer(text):
            subj, obj = normalize(match.group(1)), normalize(match.group(2))
            triples.append(Triple(subj, "supplier_of", obj, doc_id))
            mentions[subj].add(doc_id)
            mentions[obj].add(doc_id)
        for match in CEO_RE.finditer(text):
            subj, obj = normalize(match.group(1)), normalize(match.group(2))
            triples.append(Triple(subj, "ceo_is", obj, doc_id))
            mentions[subj].add(doc_id)
            mentions[obj].add(doc_id)
    return triples, mentions


def edges() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    triples, mentions = extract()
    for triple in triples:
        graph[triple.subject].add(triple.obj)
        graph[triple.obj].add(triple.subject)
    for entity, doc_ids in mentions.items():
        for doc_id in doc_ids:
            graph[entity].add(doc_id)
            graph[doc_id].add(entity)
    return graph


def ppr(seed: dict[str, float], graph: dict[str, set[str]],
        alpha: float = 0.85, steps: int = 30) -> dict[str, float]:
    nodes = list(graph)
    rank = {node: 0.0 for node in nodes}
    total_seed = sum(seed.values()) or 1.0
    for node in nodes:
        rank[node] = seed.get(node, 0.0) / total_seed
    for _ in range(steps):
        nxt = {node: 0.0 for node in nodes}
        for node in nodes:
            neighbors = graph.get(node, set())
            if not neighbors:
                continue
            share = rank[node] / len(neighbors)
            for neighbor in neighbors:
                nxt[neighbor] += share
        for node in nodes:
            rank[node] = (1 - alpha) * (seed.get(node, 0.0) / total_seed) + alpha * nxt[node]
    return rank


def vector_topk(query: str, k: int = 2) -> list[tuple[str, float]]:
    def grams(text: str) -> set[str]:
        clean = "".join(ch for ch in text.lower() if not ch.isspace())
        return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}

    q = grams(query)
    scored = []
    for doc_id, text in DOCS:
        overlap = len(q & grams(text))
        scored.append((doc_id, overlap / max(1, len(q))))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]
