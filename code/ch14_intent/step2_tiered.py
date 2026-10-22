"""第 14 章 · 第 2 级：三级路由 —— 规则 → 小模型 → 大模型 → 人工。

运行：
    python code/ch14_intent/step2_tiered.py

新增的一个概念：**分级决策（tiered routing）**。

意图识别不是"分类问题"，是"**这条请求值得花多少钱来判断**"。

    L1 规则    成本 0      覆盖高频、明确、无歧义的
    L2 小模型  成本低       覆盖长尾、带上下文
    L3 大模型  成本高       兜底高价值/高风险的
    兜底       人工         判不出来就必须承认判不出来

⚠️ 这一级用"假模型"模拟小模型和大模型的能力差异（小模型对"一句多意图"容易错），
   以便可复现地展示"分级"的价值。真实模型请用 demo_router_llm.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- 意图与路由

ROUTES = {
    "refund": "refund_flow",
    "shipping": "logistics_flow",
    "complaint": "complaint_flow",
    "product_qa": "qa_rag",
    "chitchat": "chitchat",
    "unknown": "human_handoff",
}

RULES = [
    ("refund", ("退款", "退货", "退钱")),
    ("shipping", ("物流", "快递", "什么时候到", "发货", "签收")),
    ("complaint", ("投诉", "举报", "12315")),
]

CASES = [
    ("我要退款", "refund"),
    ("退款怎么还没到账", "refund"),
    ("我的快递到哪了", "shipping"),
    ("我要投诉你们", "complaint"),
    ("我要退款但是物流也不更新", "refund"),
    ("这个耳机参数怎么样", "product_qa"),
    ("东西到现在还没影儿", "shipping"),
    ("在吗", "chitchat"),
    ("我要退款，顺便问下耳机参数", "refund"),
    ("不要了，别再发货了", "shipping"),
    ("这个尺码支持退换吗", "refund"),
]


# ---------------------------------------------------------------- 假模型

@dataclass
class FakeSmallModel:
    """小模型：看得懂常见表达，遇到"一句多意图"容易只抓到一半。"""

    calls: int = 0
    cost_per_call: float = 0.0008

    def classify(self, text: str) -> tuple[str, float]:
        self.calls += 1
        rules_hit = [i for i, kws in RULES if any(k in text for k in kws)]
        if len(rules_hit) > 1:
            # 小模型的典型毛病：只输出一个，不给"我不确定"
            return rules_hit[-1], 0.72
        if rules_hit:
            return rules_hit[0], 0.82
        if "参数" in text or "怎么样" in text:
            return "product_qa", 0.80
        if "还没影" in text:
            return "shipping", 0.55          # ＜ 阈值，会被升级
        if "在吗" in text:
            return "chitchat", 0.90
        return "unknown", 0.40


@dataclass
class FakeLargeModel:
    """大模型：能处理多意图，且会给出更合理的置信度。"""

    calls: int = 0
    cost_per_call: float = 0.0043

    def classify(self, text: str) -> tuple[str, float]:
        self.calls += 1
        if "退款" in text and "物流" in text:
            return "refund", 0.88            # 主诉求是退款
        if "退款" in text and "参数" in text:
            return "refund", 0.85
        if "退款" in text:
            return "refund", 0.95
        if "快递" in text or "物流" in text:
            return "shipping", 0.93
        if "投诉" in text:
            return "complaint", 0.94
        if "参数" in text:
            return "product_qa", 0.90
        if "在吗" in text:
            return "chitchat", 0.92
        if "还没影" in text:
            return "shipping", 0.86
        return "unknown", 0.35


# ---------------------------------------------------------------- 三级路由

@dataclass
class Decision:
    intent: str
    route: str
    level: str
    confidence: float
    cost: float


@dataclass
class TieredRouter:
    small: FakeSmallModel = field(default_factory=FakeSmallModel)
    large: FakeLargeModel = field(default_factory=FakeLargeModel)
    threshold: float = 0.75

    def route(self, text: str) -> Decision:
        # L1 规则：只在「唯一命中」时下判断
        hits = {i for i, kws in RULES if any(k in text for k in kws)}
        if len(hits) == 1:
            intent = hits.pop()
            return Decision(intent, ROUTES[intent], "rule", 0.9, 0.0)

        # L2 小模型
        intent, conf = self.small.classify(text)
        if conf >= self.threshold:
            return Decision(intent, ROUTES[intent], "small", conf, self.small.cost_per_call)

        # L3 大模型
        intent, conf = self.large.classify(text)
        if conf >= self.threshold:
            return Decision(intent, ROUTES[intent], "large", conf,
                            self.small.cost_per_call + self.large.cost_per_call)

        # 兜底：承认判不出来
        return Decision("unknown", ROUTES["unknown"], "fallback", conf,
                        self.small.cost_per_call + self.large.cost_per_call)


def main() -> None:
    router = TieredRouter()

    print("=" * 84)
    print("第 2 级：三级路由")
    print("=" * 84)
    print(f"{'输入':<24}{'期望':<12}{'判定':<12}{'层级':<10}{'置信':>6}  成本")
    print("-" * 84)

    right, total_cost = 0, 0.0
    levels: dict[str, int] = {}
    for text, expect in CASES:
        d = router.route(text)
        total_cost += d.cost
        levels[d.level] = levels.get(d.level, 0) + 1
        if d.intent == expect:
            right += 1
        print(f"{text:<24}{expect:<12}{d.intent:<12}{d.level:<10}{d.confidence:>6.2f}  ¥{d.cost:.4f}")

    print(f"\n  准确率 {right}/{len(CASES)} = {right / len(CASES):.0%}   总成本 ¥{total_cost:.4f}")
    print(f"  层级分布：{levels}")

    print("\n" + "=" * 84)
    print("对照：全用大模型 / 全用规则")
    print("=" * 84)
    all_large_cost = len(CASES) * FakeLargeModel.cost_per_call
    # 对照：全用规则的准确率（用 step1 的朴素实现算）
    rule_right = sum(
        1 for text, expect in CASES
        if (hits := {i for i, kws in RULES if any(k in text for k in kws)}) and len(hits) == 1
        and hits.pop() == expect
    )
    print(f"  全用规则  ：准确率 {rule_right}/{len(CASES)}   成本 ¥0.0000")
    print(f"  全用大模型：成本 ¥{all_large_cost:.4f}（每条都调一次，含本来就简单的）")
    print(f"  三级路由  ：准确率 {right}/{len(CASES)}   成本 ¥{total_cost:.4f}"
          f"   → 相比全用大模型省 {1 - total_cost / all_large_cost:.0%}")
    print()
    print("  👉 省下的钱来自「L1 规则拦下的那几条」—— 它们零成本、零延迟。")
    print("     规则层的价值不是准确率高，是**把最便宜的部分剥离出来**。")
    print()
    print("  ⚠️ 注意最后一行「这个尺码支持退换吗」走了 fallback：")
    print("     规则命中「退货」→ 但语义是「询问政策」而不是「要退货」。")
    print("     **判不出来就转人工，这是设计，不是失败。**")

    print("\n" + "=" * 84)
    print("两个必须注意的细节")
    print("=" * 84)
    print("  1. 置信度不是概率：模型说 0.82 不代表 82% 正确，")
    print("     阈值必须用真实样本分桶标定（第 37 章）。")
    print("  2. fallback 是合法的：判不出来就转人工，不要硬猜。")
    print("     「强行分类」的代价远大于「多转一次人工」。")


if __name__ == "__main__":
    main()
