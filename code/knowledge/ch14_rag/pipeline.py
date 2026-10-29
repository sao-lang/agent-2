"""RAG 的四环节与三种拼装坏法，以及一次坏回答归因到哪一环。

不联网：检索用字符 2-gram 余弦代替嵌入，生成用"抽取式假模型"代替模型。
两处都是代用品，用来把环节之间的边界讲清楚；真实组件的版本见 langchain_rag.py。
"""

from __future__ import annotations

import math
import re
from collections import Counter

DOCS = [
    {"id": "d1", "text": "质量问题退货，运费由商家承担。非质量问题退货，运费由买家承担。"},
    {"id": "d2", "text": "签收后 7 天内可申请无理由退货，商品需保持未拆封状态。"},
    {"id": "d3", "text": "发票可在订单页申请，开票时限为下单后 30 天。"},
    {"id": "d4", "text": "生鲜类商品不支持无理由退货，质量问题请在签收后 24 小时内拍照反馈。"},
]

CITE = re.compile(r"^\[(d\d+)\]")


# ---------------------------------------------------------------- 环节一：检索

def grams(text: str, n: int = 2) -> Counter:
    text = re.sub(r"\s+", "", text)
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))


def cosine(a: Counter, b: Counter) -> float:
    num = sum(a[k] * b[k] for k in set(a) & set(b))
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def retrieve(query: str, docs: list[dict], k: int = 2) -> list[tuple[dict, float]]:
    q = grams(query)
    scored = [(d, cosine(q, grams(d["text"]))) for d in docs]
    return sorted(scored, key=lambda x: -x[1])[:k]


# ---------------------------------------------------------------- 环节二：拼装

def assemble_drop(question: str, hits: list[tuple[dict, float]],
                  budget: int = 120) -> str:
    """坏法一的反面：超预算就丢掉整条，块保持完整、带编号。"""
    blocks, used = [], 0
    for d, _ in hits:
        if used + len(d["text"]) > budget:
            continue
        blocks.append(f"[{d['id']}] {d['text']}")
        used += len(d["text"])
    return "\n".join(blocks)


def assemble_truncate(question: str, hits: list[tuple[dict, float]],
                      budget: int = 120) -> str:
    """坏法二：从末尾截断，块被切成半个句子。"""
    text = "\n".join(f"[{d['id']}] {d['text']}" for d, _ in hits)
    return text[:budget]


def assemble_no_id(question: str, hits: list[tuple[dict, float]],
                   budget: int = 120) -> str:
    """坏法三：只拼正文，不带编号。"""
    return "\n".join(d["text"] for d, _ in hits)[:budget]


# ---------------------------------------------------------------- 环节三：生成

def generate(question: str, context: str) -> dict:
    """抽取式假模型：只从带编号的参考资料里挑最相关的一句。"""
    q = grams(question)
    best, best_score = None, 0.0
    for line in context.splitlines():
        m = CITE.match(line)
        if not m:
            continue
        for sent in re.split(r"[。；]", CITE.sub("", line).strip()):
            s = cosine(q, grams(sent))
            if s > best_score:
                best, best_score = (m.group(1), sent), s
    if best is None:
        return {"answer": "资料里没有相关内容。", "citations": [], "score": 0.0}
    return {"answer": best[1], "citations": [best[0]], "score": round(best_score, 3)}


# ---------------------------------------------------------------- 环节四：引用

def citations_ok(answer: str, citations: list[str], docs: list[dict]) -> bool:
    """每个引用必须存在，且答案能在被引文档里找到原文。"""
    by_id = {d["id"]: d["text"] for d in docs}
    for c in citations:
        if c not in by_id or answer not in by_id[c]:
            return False
    return True


# ---------------------------------------------------------------- 归因

def attribute(question: str, docs: list[dict], k: int = 2, budget: int = 120) -> dict:
    hits = retrieve(question, docs, k)
    retrieved = [d["id"] for d, _ in hits]
    context = assemble_drop(question, hits, budget)
    kept = [m.group(1) for m in (CITE.match(l) for l in context.splitlines()) if m]
    out = generate(question, context)
    return {
        "question": question,
        "retrieved": [(d["id"], round(s, 3)) for d, s in hits],
        "kept": kept,
        "answer": out["answer"],
        "citations": out["citations"],
        "abstained": "没有相关内容" in out["answer"],
        "citation_ok": citations_ok(out["answer"], out["citations"], docs),
    }


def diagnose(r: dict, expect: str) -> str:
    """按顺序检查四个环节，返回最先坏掉的那一环。"""
    if expect not in [i for i, _ in r["retrieved"]]:
        return "检索：期望的文档没被召回"
    if expect not in r["kept"]:
        return "拼装：召回了但没进上下文"
    if r["abstained"]:
        return "生成：上下文里有资料却答了没有"
    if not r["citation_ok"]:
        return "引用：答案与引用对不上"
    return "四环都没坏"


CASES = [
    ("生鲜坏了怎么退", "d4", 120, "正常"),
    ("发票什么时候能开", "d3", 120, "正常"),
    ("质量问题退货运费谁出", "d1", 10, "拼装预算 10 字"),
    ("耳机保修几年", "d9", 120, "知识库没这条"),
]

ASSEMBLERS = [
    ("丢整条（带编号）", assemble_drop),
    ("末尾截断（带编号）", assemble_truncate),
    ("只拼正文（无编号）", assemble_no_id),
]


if __name__ == "__main__":
    print("=== 1. 四个问题，逐环节看 ===")
    for q, expect, budget, label in CASES:
        r = attribute(q, DOCS, k=2, budget=budget)
        print(f"\n  [{label}] {q}")
        print(f"    检索 {r['retrieved']}")
        print(f"    进上下文 {r['kept']}")
        print(f"    回答 {r['answer']!r}  引用 {r['citations']}")
        print(f"    归因 -> {diagnose(r, expect)}")

    print()
    print("=== 2. 三种拼装坏法，同一条检索结果 ===")
    q = "生鲜坏了怎么退"
    hits = retrieve(q, DOCS, k=2)
    print(f"  检索结果 {[(d['id'], round(s, 3)) for d, s in hits]}")
    for name, fn in ASSEMBLERS:
        ctx = fn(q, hits, budget=30)
        out = generate(q, ctx)
        print(f"\n  [{name}] 上下文 {len(ctx)} 字")
        print(f"    {ctx!r}")
        print(f"    回答 {out['answer']!r}  引用 {out['citations']}")

    print()
    print("=== 3. 生成环节编造引用 ===")
    fake = {"answer": "生鲜类商品不支持退货。", "citations": ["d9"]}
    print(f"  引用 {fake['citations']} 校验 "
          f"{'通过' if citations_ok(fake['answer'], fake['citations'], DOCS) else '不通过'}")
    fake2 = {"answer": "生鲜类商品七天内可退。", "citations": ["d2"]}
    print(f"  引用 {fake2['citations']} 校验 "
          f"{'通过' if citations_ok(fake2['answer'], fake2['citations'], DOCS) else '不通过'}"
          "  <- 引用存在，但被引文档里没有这句话")

