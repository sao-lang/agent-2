"""模板编译替身：按主题生成条目骨架。"""

from __future__ import annotations

from dataclasses import dataclass, field

from data import DOCS

TOPIC_BY_DOC = {
    "d01": "退款政策", "d02": "退款政策",
    "d03": "定制商品",
    "d04": "退款到账", "d05": "退款到账",
    "d06": "物流", "d07": "物流", "d08": "物流",
    "d09": "发票", "d10": "发票", "d11": "发票",
    "d12": "会员", "d13": "会员", "d14": "会员",
    "d15": "售后", "d16": "售后", "d17": "售后",
    "d18": "支付", "d19": "支付", "d20": "支付",
}

LINKS = {
    "退款政策": ["退款到账", "定制商品"],
    "退款到账": ["退款政策"],
    "定制商品": ["退款政策"],
    "物流": ["售后"],
    "售后": ["物流", "退款政策"],
}


@dataclass
class Entry:
    title: str
    body: str
    sources: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


def compile_entries(include_gaps: bool = True) -> dict[str, Entry]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for doc_id, _topic, text in DOCS:
        topic = TOPIC_BY_DOC[doc_id]
        if not include_gaps and doc_id == "d05":
            continue  # v1 漏掉“节假日延迟”
        if not include_gaps and doc_id == "d17":
            continue  # v1 漏掉“问题照片”
        grouped.setdefault(topic, []).append((doc_id, text))

    entries: dict[str, Entry] = {}
    for topic, rows in grouped.items():
        body = "\n".join(f"- {text}（来源：{doc_id}）" for doc_id, text in rows)
        entries[topic] = Entry(
            title=topic,
            body=body,
            sources=[doc_id for doc_id, _ in rows],
            links=LINKS.get(topic, []),
        )
    return entries


def rag_topk(query: str, k: int = 3) -> list[tuple[str, str, float]]:
    def grams(text: str) -> set[str]:
        clean = "".join(ch for ch in text.lower() if not ch.isspace())
        return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}

    q = grams(query)
    scored = []
    for doc_id, _topic, text in DOCS:
        score = len(q & grams(text)) / max(1, len(q))
        scored.append((doc_id, text, score))
    scored.sort(key=lambda row: row[2], reverse=True)
    return scored[:k]
