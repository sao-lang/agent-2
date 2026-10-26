"""第 31 章产出：三级意图识别与路由。

三级（从便宜到贵，逐级升级）：
  L1 规则       —— 关键词/正则，0 成本，覆盖高频明确意图
  L2 小模型分类 —— 结构化输出，成本低，覆盖大部分长尾
  L3 大模型兜底 —— 只有前两级都"不确定"时才用

为什么分级？
因为客服系统里 70% 的请求是重复的几种意图，用大模型分类是纯浪费。
分级设计能把意图识别成本压到原来的 1/5 甚至更低。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    REFUND = "refund"  # 退款/退货
    SHIPPING = "shipping"  # 物流
    PRODUCT_QA = "product_qa"  # 商品咨询
    COMPLAINT = "complaint"  # 投诉
    CHITCHAT = "chitchat"  # 闲聊
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    route: str  # 走哪个处理链
    level: str  # "rule" | "small" | "large"
    cost: float = 0.0
    latency_ms: float = 0.0
    reason: str = ""


# ============================================================ L1 规则

RULES: list[tuple[Intent, tuple[str, ...], str]] = [
    (Intent.REFUND, ("退款", "退货", "退钱", "不要了"), "refund_flow"),
    (Intent.SHIPPING, ("物流", "快递", "什么时候到", "发货", "签收"), "logistics_flow"),
    (Intent.COMPLAINT, ("投诉", "举报", "太差", "气死", "12315"), "complaint_flow"),
    (Intent.PRODUCT_QA, ("怎么样", "参数", "颜色", "尺码", "支持", "能不能"), "qa_rag"),
    (Intent.CHITCHAT, ("你好", "在吗", "谢谢", "哈哈"), "chitchat"),
]


def rule_classify(text: str) -> IntentResult | None:
    """规则层：命中即返回，未命中等下一级。"""
    hits: list[tuple[Intent, str]] = []
    for intent, keywords, route in RULES:
        for k in keywords:
            if k in text:
                hits.append((intent, route))
                break

    if not hits:
        return None

    # 多个意图都命中 → 规则层无法判断优先级，交给上一层
    if len({h[0] for h in hits}) > 1:
        return None

    intent, route = hits[0]
    return IntentResult(intent=intent, confidence=0.9, route=route, level="rule", reason="关键词命中")


# ============================================================ L2 小模型

CLASSIFY_PROMPT = """把用户消息分类到唯一一个意图。只输出 JSON。

可选意图：refund / shipping / product_qa / complaint / chitchat / unknown

规则：
- 提到退款、退货、退钱 → refund
- 问物流、快递、到货时间 → shipping
- 问商品参数、功能、适用性 → product_qa
- 表达不满、要投诉 → complaint
- 打招呼、道谢 → chitchat
- 无法判断 → unknown，并把 confidence 设为 0

输出格式：{{"intent": "...", "confidence": 0.0~1.0, "reason": "一句话"}}

用户消息：{text}"""

ROUTE_MAP = {
    Intent.REFUND: "refund_flow",
    Intent.SHIPPING: "logistics_flow",
    Intent.PRODUCT_QA: "qa_rag",
    Intent.COMPLAINT: "complaint_flow",
    Intent.CHITCHAT: "chitchat",
    Intent.UNKNOWN: "fallback",
}


def llm_classify(llm: Any, text: str, cheap: bool = True) -> IntentResult:
    """用模型做分类。cheap=True 时用便宜模型（L2），False 时用主模型（L3）。"""
    t0 = __import__("time").perf_counter()
    msg = llm.invoke(CLASSIFY_PROMPT.format(text=text))
    raw = msg.content if isinstance(msg.content, str) else str(msg.content)

    try:
        # 容忍 ```json 包裹
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        intent = Intent(data["intent"])
        conf = float(data.get("confidence", 0.0))
        reason = data.get("reason", "")
    except Exception as e:  # noqa: BLE001
        return IntentResult(Intent.UNKNOWN, 0.0, "fallback", "large",
                            reason=f"解析失败：{type(e).__name__}")

    return IntentResult(
        intent=intent,
        confidence=conf,
        route=ROUTE_MAP.get(intent, "fallback"),
        level="small" if cheap else "large",
        latency_ms=(__import__("time").perf_counter() - t0) * 1000,
        reason=reason,
    )


# ============================================================ 三级路由器

@dataclass
class IntentRouter:
    """分级路由：能用规则就不调模型，能用小模型就不调大模型。"""

    small_llm: Any | None = None
    large_llm: Any | None = None
    threshold: float = 0.6  # 置信度低于此值 → 升级到下一级
    stats: dict[str, int] = field(default_factory=lambda: {"rule": 0, "small": 0, "large": 0, "fallback": 0})

    def route(self, text: str) -> IntentResult:
        # L1
        r = rule_classify(text)
        if r:
            self.stats["rule"] += 1
            return r

        # L2
        if self.small_llm is not None:
            r = llm_classify(self.small_llm, text, cheap=True)
            if r.confidence >= self.threshold and r.intent is not Intent.UNKNOWN:
                self.stats["small"] += 1
                return r

        # L3
        if self.large_llm is not None:
            r = llm_classify(self.large_llm, text, cheap=False)
            if r.confidence >= self.threshold and r.intent is not Intent.UNKNOWN:
                self.stats["large"] += 1
                return r

        self.stats["fallback"] += 1
        return IntentResult(Intent.UNKNOWN, 0.0, "fallback", "fallback", reason="全部层级都未确定")


# ============================================================ 评测

@dataclass
class EvalCase:
    text: str
    expected: Intent
    # 期望的层级（用于检查"该走规则的是不是走了模型"）
    cheapest_level: str = "rule"


def evaluate(router: IntentRouter, cases: list[EvalCase]) -> dict[str, Any]:
    correct = 0
    by_level: dict[str, int] = {}
    errors = []
    for c in cases:
        r = router.route(c.text)
        by_level[r.level] = by_level.get(r.level, 0) + 1
        if r.intent == c.expected:
            correct += 1
        else:
            errors.append((c.text, c.expected.value, r.intent.value, r.level))

    return {
        "accuracy": correct / len(cases),
        "by_level": by_level,
        "errors": errors,
        "cost_profile": router.stats,
    }
