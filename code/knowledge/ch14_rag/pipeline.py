"""RAG 的四个环节，以及一次坏回答归因到哪一环。

不联网、不用向量库。检索用字符 2-gram 余弦相似度代替嵌入，
回答用脚本化的"抽取式生成"代替模型，这样归因过程不依赖任何外部服务。
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

def assemble(question: str, hits: list[tuple[dict, float]], budget: int = 200) -> dict:
    """把检索结果拼进提示词。budget 是给参考资料的字数预算。"""
    blocks, used = [], 0
    for d, _ in hits:
        if used + len(d["text"]) > budget:
            continue                      # 超预算就丢掉整条
        blocks.append(f"[{d['id']}] {d['text']}")
        used += len(d["text"])
    return {"question": question, "context": "\n".join(blocks), "used_chars": used}


# ---------------------------------------------------------------- 环节三：生成

def generate(prompt: dict) -> dict:
    """抽取式假模型：只从参考资料里挑最相关的一句，并标注来源。"""
    q = grams(prompt["question"])
    best, best_score = None, 0.0
    for line in prompt["context"].splitlines():
        m = CITE.match(line)
        if not m:
            continue
        for sent in re.split(r"[。；]", CITE.sub("", line).strip()):
            s = cosine(q, grams(sent))
            if s > best_score:
                best, best_score = (m.group(1), sent), s
    if best is None:
        return {"answer": "资料里没有相关内容。", "citations": [], "score": 0.0}
    return {"answer": best[1], "citations": [best[0]], "score": best_score}


# ---------------------------------------------------------------- 环节四：引用

def citations_ok(answer: str, citations: list[str], docs: list[dict]) -> bool:
    """每个引用必须存在，且答案能在被引文档里找到原文。"""
    by_id = {d["id"]: d["text"] for d in docs}
    for c in citations:
        if c not in by_id or answer not in by_id[c]:
            return False
    return True


# ---------------------------------------------------------------- 归因

def attribute(question: str, docs: list[dict], k: int = 2, budget: int = 200) -> dict:
    """跑一遍完整链路，然后逐环节检查。"""
    hits = retrieve(question, docs, k)
    retrieved = [d["id"] for d, _ in hits]

    prompt = assemble(question, hits, budget)
    kept = [m.group(1) for m in (CITE.match(l) for l in prompt["context"].splitlines()) if m]

    out = generate(prompt)
    abstained = "没有相关内容" in out["answer"]

    return {
        "question": question,
        "retrieved": [(d["id"], round(s, 3)) for d, s in hits],
        "kept": kept,
        "answer": out["answer"],
        "citations": out["citations"],
        "abstained": abstained,
        "citation_ok": citations_ok(out["answer"], out["citations"], docs),
    }


def diagnose(r: dict, expect: str) -> str:
    """按顺序检查四个环节，返回最先坏掉的那一环。"""
    if expect not in [i for i, _ in r["retrieved"]]:
        return "检索：期望的文档没被召回"
    if expect not in r["kept"]:
        return "拼装：召回了但没进上下文"
    if r["abstained"]:
        return "生成：上下文里有资料却答了'没有'"
    if not r["citation_ok"]:
        return "引用：答案与引用对不上"
    return "四环都没坏"


CASES = [
    # (问题, 期望文档, k, 拼装预算, 说明)
    ("生鲜坏了怎么退", "d4", 2, 200, "正常"),
    ("质量问题退货运费谁出", "d1", 2, 200, "正常"),
    ("发票什么时候能开", "d3", 2, 200, "正常"),
    ("质量问题退货运费谁出", "d1", 2, 10, "拼装预算 10 字"),
    ("耳机保修几年", "d9", 2, 200, "知识库没这条"),
]


if __name__ == "__main__":
    print("=== 1. 五个问题，逐环节看 ===")
    for q, expect, k, budget, label in CASES:
        r = attribute(q, DOCS, k=k, budget=budget)
        print(f"\n  [{label}] {q}")
        print(f"    检索 {r['retrieved']}")
        print(f"    进上下文 {r['kept']}")
        print(f"    回答 {r['answer']!r}  引用 {r['citations']}")
        print(f"    归因 -> {diagnose(r, expect)}")

    print()
    print("=== 2. 生成环节编造引用 ===")
    fake = {"answer": "生鲜类商品不支持退货。", "citations": ["d9"]}
    print(f"  引用 {fake['citations']} 校验 "
          f"{'通过' if citations_ok(fake['answer'], fake['citations'], DOCS) else '不通过'}")
    fake2 = {"answer": "生鲜类商品七天内可退。", "citations": ["d2"]}
    print(f"  引用 {fake2['citations']} 校验 "
          f"{'通过' if citations_ok(fake2['answer'], fake2['citations'], DOCS) else '不通过'}"
          "  <- 引用了真实文档，但文档里没有这句话")
