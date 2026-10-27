"""三级路由：规则 → 小模型 → 大模型，外加兜底。

不联网。小模型与大模型都是脚本化的假后端，按问题内容给出固定分数，
用来演示分数的含义（像不像已知意图 / 自信地答 / 不确定）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 路由表

FAQ_SAMPLES = {
    "退货运费谁出": "质量问题由商家承担，非质量问题由买家承担。",
    "发票怎么开": "下单后 30 天内可在订单页申请电子发票。",
    "几天能到": "默认 48 小时内发货，偏远地区 4-5 天。",
}

# 规则层：命中即短路，不花一次模型调用
RULES = [
    ("faq_exact", lambda q: q.strip() in FAQ_SAMPLES),
    ("order_id", lambda q: "A1" in q and any(c.isdigit() for c in q)),
    ("shipping", lambda q: "几天" in q and "到" in q),
]


# ---------------------------------------------------------------- 假后端

@dataclass
class SmallModel:
    """小模型替身：对每个已知意图给一个相似度分数。原理演示，不是实测。"""
    labels: dict[str, list[str]] = field(default_factory=lambda: {
        "refund": ["能退", "退货", "退吗", "退款"],
        "status": ["状态", "到哪", "物流", "签收"],
    })

    def score(self, question: str) -> list[tuple[str, float]]:
        out = []
        for label, words in self.labels.items():
            hit = sum(1 for w in words if w in question)
            out.append((label, min(0.99, hit * 0.45)))
        return sorted(out, key=lambda x: -x[1])

    def answer(self, question: str) -> tuple[str, float]:
        """小模型自己作答，返回 (答案, 自报置信度)。分数同样是脚本化的。"""
        if "几天能到" in question or "多久" in question:
            return "一般 48 小时内发货。", 0.91     # 答对了
        if "保修" in question:
            return "保修三年，全城上门。", 0.88     # 编的
        return "", 0.0


@dataclass
class BigModel:
    """大模型替身：总是能答，用来兜住小模型不敢答的部分。"""
    calls: int = 0

    def answer(self, question: str) -> str:
        self.calls += 1
        if "保修" in question:
            return "政策里只写了 7 天无理由退货，没有保修条款。"
        return f"（大模型作答）{question} 的处理结果。"


# ---------------------------------------------------------------- 三级路由

SMALL_MODEL_THRESHOLD = 0.6
ANSWER_CONFIDENCE_THRESHOLD = 0.8


def route(question: str, small: SmallModel, big: BigModel) -> dict:
    """返回 {tier, confidence, answer, reason}。tier 取值：rule / small / big。"""
    for name, cond in RULES:
        if cond(question):
            if name == "faq_exact":
                return {"tier": "rule", "confidence": 1.0,
                        "answer": FAQ_SAMPLES[question.strip()], "reason": "命中 FAQ 原文"}
            return {"tier": "rule", "confidence": 1.0,
                    "answer": None, "reason": f"命中 {name} 规则，直接进对应链路"}

    ranked = small.score(question)
    label, score = ranked[0]
    if score < SMALL_MODEL_THRESHOLD:
        return {"tier": "big", "confidence": 1.0,
                "answer": big.answer(question),
                "reason": f"小模型最高分 {score:.2f}，不认识这个问题"}

    answer, conf = small.answer(question)
    if conf >= ANSWER_CONFIDENCE_THRESHOLD:
        return {"tier": "small", "confidence": conf,
                "answer": answer, "reason": f"小模型判为 {label}，自报 {conf:.2f}"}

    return {"tier": "big", "confidence": 1.0,
            "answer": big.answer(question),
            "reason": f"小模型判为 {label} 但不敢答（自报 {conf:.2f}）"}


# ---------------------------------------------------------------- 兜底与指标

def fallback(reason: str) -> dict:
    """兜底。不是失败：有确定回复、有转人工标记、有原因记录。"""
    return {
        "tier": "fallback",
        "reply": "这个问题需要人工确认，已为你转接，预计 3 分钟内回复。",
        "handoff": True,
        "reason": reason,
    }


def report(results: list[dict]) -> None:
    c = Counter(r["tier"] for r in results)
    n = len(results)
    print(f"  样本 {n} 条：" + "  ".join(f"{k}={v}（{v / n:.0%}）" for k, v in c.items()))
    fb = c["fallback"] / n
    print(f"  兜底率 {fb:.0%}" + ("  <- 超过 10% 需要查原因" if fb > 0.10 else ""))


if __name__ == "__main__":
    questions = [
        "退货运费谁出",
        "这个订单几天能到",
        "订单 A1001 还能退吗",
        "这个耳机保修几年",
        "耳机退款要几天",
        "帮我写一首关于秋天的诗",
    ]
    small, big = SmallModel(), BigModel()

    print("=== 1. 一条请求一条请求地看 ===")
    for q in questions:
        r = route(q, small, big)
        print(f"  {q!r:34} -> {r['tier']:<6} {r['reason']}")
    print(f"  大模型被调用 {big.calls} 次 / 共 {len(questions)} 条请求")

    print()
    print("=== 2. 兜底不是失败 ===")
    results = [route(q, small, big) for q in questions]
    results.append(fallback("知识库里没有保修条款"))
    report(results)

    print()
    print("=== 3. 置信度不是概率 ===")
    for q in ["我要退款，但先问物流", "物流到哪了，顺便退款"]:
        print(f"  {q!r:20} 分数 {small.score(q)}")
    print("  关键词命中数一变，分数就翻倍：它衡量的是'像不像'，不是'答对的可能'")
