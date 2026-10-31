"""LLM Wiki 原理演示：模板编译 + 诊断探针 + 增量重编译。

真实系统把 write_entry() 换成 LLM 长文生成；这里只用标准库。
"""

from __future__ import annotations

DOCS = [
    ("d1", "退货政策", "签收后 7 天内可退。"),
    ("d2", "退货例外", "例外：定制商品不适用 7 天无理由退货。"),
    ("d3", "退款时效", "退款到账时间：原支付方式 1-3 个工作日。"),
    ("d4", "运费", "质量问题由商家承担运费，非质量问题由买家承担。"),
    ("d5", "会员", "PLUS 会员退货窗口延长到 15 天。"),
    ("d6", "发票", "退款后发票需退回。"),
    ("d7", "客服", "退款问题可转人工客服。"),
    ("d8", "换货", "7 天内可换货，需保持商品完好。"),
]


def compile_all(include_exceptions: bool = False) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    entries["退货资格"] = {
        "title": "退货资格",
        "text": "签收后 7 天内可退；PLUS 会员延长到 15 天。"
                + ("定制商品不适用 7 天无理由退货。" if include_exceptions else ""),
        "sources": ["d1", "d2", "d5"],
        "links": ["退款时效", "运费"],
    }
    entries["退款时效"] = {
        "title": "退款时效",
        "text": "退款到原支付方式，1-3 个工作日到账。",
        "sources": ["d3"], "links": ["退货资格"],
    }
    entries["运费"] = {
        "title": "运费",
        "text": "质量问题商家承担，非质量问题买家承担。",
        "sources": ["d4"], "links": ["退货资格"],
    }
    entries["发票"] = {
        "title": "发票", "text": "退款后发票需退回。",
        "sources": ["d6"], "links": [],
    }
    entries["换货"] = {
        "title": "换货", "text": "7 天内可换货，需保持商品完好。",
        "sources": ["d8"], "links": ["退货资格"],
    }
    entries["客服"] = {
        "title": "客服", "text": "退款问题可转人工客服。",
        "sources": ["d7"], "links": [],
    }
    return entries


def answer_from_wiki(question: str, entries: dict[str, dict]) -> str:
    if "PLUS" in question or "会员" in question:
        return entries["退货资格"]["text"]
    if "定制" in question:
        text = entries["退货资格"]["text"]
        return text if "定制" in text else "定制商品按 7 天政策处理。"
    if "到账" in question or "多久" in question:
        return entries["退款时效"]["text"]
    if "运费" in question:
        return entries["运费"]["text"]
    if "发票" in question:
        return entries["发票"]["text"]
    if "换" in question:
        return entries["换货"]["text"]
    return entries["退货资格"]["text"]


def bigrams(text: str) -> set[str]:
    clean = "".join(ch for ch in text if not ch.isspace())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def rag_top3(question: str) -> list[tuple[str, str, float]]:
    q = bigrams(question)
    rows = []
    for doc_id, title, text in DOCS:
        score = len(q & bigrams(text + title)) / max(1, len(q))
        rows.append((doc_id, text, score))
    rows.sort(key=lambda item: item[2], reverse=True)
    return rows[:3]


PROBES = [
    ("定制商品能退吗？", "不适用"),
    ("退款多久到账？", "1-3 个工作日"),
    ("退货运费谁出？", "质量问题"),
    ("退款后发票怎么办？", "退回"),
    ("PLUS 会员能退多久？", "15 天"),
]


def probe(entries: dict[str, dict]) -> list[tuple[str, bool, str]]:
    rows = []
    for question, keyword in PROBES:
        answer = answer_from_wiki(question, entries)
        rows.append((question, keyword in answer, answer))
    return rows


def render(entries: dict[str, dict]) -> str:
    lines = []
    for name, entry in entries.items():
        lines.append(f"## {entry['title']}")
        lines.append(entry["text"])
        lines.append(f"来源：{', '.join(entry['sources'])}；链接：{', '.join(entry['links'])}")
        lines.append("")
    return "\n".join(lines)
