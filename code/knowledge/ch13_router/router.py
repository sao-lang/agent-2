"""四级分流：规则 → 小模型 → 大模型，外加兜底与范围外。

不联网。小模型与大模型是脚本化替身，按输入给出固定分数，
用来演示"分数是什么"与"判据放在哪"，不代表任何真实模型的实测表现。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 请求分类

# 四类请求，按"答案在哪"分，而不是按长短分。
LANES = {
    "faq": "答案在固定答复里",
    "single": "一次模型调用能答",
    "loop": "需要查工具、需要多步",
    "out_of_scope": "不属于本系统的服务范围",
}

FAQ_SAMPLES = {
    "退货运费谁出": "质量问题由商家承担，非质量问题由买家承担。",
    "发票怎么开": "下单后 30 天内可在订单页申请电子发票。",
}

ORDER_ID = re.compile(r"\bA\d{4}\b")


# ---------------------------------------------------------------- 规则层

# 每条规则：(名字, 判据, 命中后去哪条路)。判据必须是纯函数：同样的输入永远同样结果。
RULES = [
    ("faq_exact", lambda q: q.strip() in FAQ_SAMPLES, "faq"),
    ("order_id", lambda q: bool(ORDER_ID.search(q)), "loop"),
    ("tracking", lambda q: "几天" in q and "到" in q, "loop"),
    ("smalltalk", lambda q: q.strip() in {"你好", "在吗"}, "faq"),
]


def rule_route(question: str) -> tuple[str, str] | None:
    """命中返回 (规则名, 目标路)，未命中返回 None。"""
    for name, cond, lane in RULES:
        if cond(question):
            return name, lane
    return None


# ---------------------------------------------------------------- 模型替身

@dataclass
class SmallModel:
    """小模型替身：意图分数用词表命中算，自报置信度是脚本写死的。

    分数与置信度都属于"原理演示"，真实系统里前者是分类头或嵌入相似度，
    后者是生成时的自报信号（不可靠，见正文）。
    """

    labels: dict[str, list[str]] = field(default_factory=lambda: {
        "refund": ["能退", "退货", "退吗", "退款"],
        "status": ["状态", "到哪", "物流", "签收"],
        "warranty": ["保修", "质保"],
    })
    version: str = "small-2026-10-a"

    def score(self, question: str) -> list[tuple[str, float]]:
        out = []
        for label, words in self.labels.items():
            hit = sum(1 for w in words if w in question)
            out.append((label, round(min(0.99, hit * 0.45), 2)))
        return sorted(out, key=lambda x: -x[1])

    def answer(self, question: str) -> tuple[str, float]:
        """返回 (答案, 自报置信度)。保修那条是没有依据的编造，用来演示放行的代价。"""
        if "几天" in question or "多久" in question:
            return "一般 48 小时内发货。", 0.91
        if "保修" in question:
            return "保修三年，全国联保。", 0.88
        return "", 0.0


@dataclass
class BigModel:
    """大模型替身：总是能答，记下被调用次数。"""
    calls: int = 0

    def answer(self, question: str) -> str:
        self.calls += 1
        if "保修" in question:
            return "现有政策文档只写了 7 天无理由退货，没有保修条款。"
        return f"（大模型作答）{question} 的处理结果。"


# ---------------------------------------------------------------- 分流主体

INTENT_THRESHOLD = 0.60          # 判"是不是一个已知意图"
ANSWER_CONFIDENCE_THRESHOLD = 0.80  # 判"这个问题它敢不敢答"

# 范围外的判据与业务规则分开：它决定的是"接不接"，不是"怎么答"。
OUT_OF_SCOPE = [
    lambda q: "写一首" in q or "讲个笑话" in q,
    lambda q: "竞争对手" in q,
]


def route(question: str, small: SmallModel, big: BigModel) -> dict:
    """返回一条路由记录。tier 取值：rule / small / big / fallback / out_of_scope。"""
    record = {"question": question, "small_version": small.version,
              "intent_threshold": INTENT_THRESHOLD}

    for cond in OUT_OF_SCOPE:
        if cond(question):
            record |= {"tier": "out_of_scope", "reason": "不属于服务范围"}
            return record

    hit = rule_route(question)
    if hit is not None:
        name, lane = hit
        record |= {"tier": "rule", "rule": name, "lane": lane,
                   "reason": f"命中 {name}"}
        if lane == "faq" and question.strip() in FAQ_SAMPLES:
            record["answer"] = FAQ_SAMPLES[question.strip()]
        return record

    label, score = small.score(question)[0]
    record |= {"label": label, "score": score}

    if score < INTENT_THRESHOLD:
        record |= {"tier": "big", "answer": big.answer(question),
                   "reason": f"意图最高分 {score:.2f} < {INTENT_THRESHOLD}"}
        return record

    answer, conf = small.answer(question)
    record["confidence"] = conf
    if conf >= ANSWER_CONFIDENCE_THRESHOLD:
        record |= {"tier": "small", "answer": answer,
                   "reason": f"判为 {label}，自报 {conf:.2f}"}
    else:
        record |= {"tier": "big", "answer": big.answer(question),
                   "reason": f"判为 {label} 但自报 {conf:.2f}，不敢答"}
    return record


def fallback(reason: str) -> dict:
    """兜底。有确定回复、有转人工标记、有原因。"""
    return {
        "tier": "fallback",
        "reply": "这个问题需要人工确认，已为你转接，预计 3 分钟内回复。",
        "handoff": True,
        "reason": reason,
    }


def report(results: list[dict]) -> None:
    c = Counter(r["tier"] for r in results)
    n = len(results)
    print("  " + "  ".join(f"{k}={v}（{v / n:.0%}）"
                           for k, v in sorted(c.items(), key=lambda kv: -kv[1])))
    fb = c["fallback"] / n
    oos = c["out_of_scope"] / n
    print(f"  兜底率 {fb:.0%}  范围外 {oos:.0%}"
          + ("  <- 兜底率超过 10% 需要查原因" if fb > 0.10 else ""))


if __name__ == "__main__":
    small, big = SmallModel(), BigModel()

    print("=== 1. 四级分流 ===")
    questions = [
        "退货运费谁出",
        "订单 A1001 还能退吗",
        "这个订单几天能到",
        "这个耳机保修几年",
        "耳机退款要几天",
        "帮我写一首关于秋天的诗",
    ]
    for q in questions:
        r = route(q, small, big)
        tier = r["tier"]
        detail = r.get("rule") or r.get("reason", "")
        print(f"  {q:<24} {tier:<13} {detail}")
    print(f"  大模型被调用 {big.calls} 次 / 共 {len(questions)} 条请求")

    print()
    print("=== 2. 兜底与范围外分开统计 ===")
    results = [route(q, small, big) for q in questions]
    results.append(fallback("知识库里没有保修条款"))
    report(results)

    print()
    print("=== 3. 同一条请求，分数随措辞变 ===")
    for q in ["我要退款，但先问物流", "物流到哪了，顺便退款"]:
        print(f"  {q:<20} {small.score(q)}")
