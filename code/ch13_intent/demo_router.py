"""第 13 章示例：三级意图路由的成本-准确率对比（不需要 API）。

运行：
    python code/ch13_intent/demo_router.py

对比三种方案：
  A. 全部用大模型分类（准，但贵）
  B. 全部用规则（便宜，但覆盖不全）
  C. 三级路由（规则 → 小模型 → 大模型）

用"虚拟模型"模拟不同层级的成本与准确率，这样结果可复现、可核算。
真实模型的准确率请用 demo_router_llm.py 在你自己的数据上测。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.intent import (  # noqa: E402
    EvalCase,
    Intent,
    IntentResult,
    IntentRouter,
    evaluate,
    rule_classify,
)


# ---------------------------------------------------------------- 测试集

CASES: list[EvalCase] = [
    # --- 高频、明确的意图（规则应该能覆盖）---
    EvalCase("我要退款", Intent.REFUND),
    EvalCase("这个能退货吗", Intent.REFUND),
    EvalCase("快递怎么还没到", Intent.SHIPPING),
    EvalCase("什么时候发货", Intent.SHIPPING),
    EvalCase("我要投诉", Intent.COMPLAINT),
    EvalCase("你好", Intent.CHITCHAT),
    # --- 有明确意图但用了不含关键词的说法（规则会漏）---
    EvalCase("钱能退回来吗", Intent.REFUND),
    EvalCase("我买错了想换个别的", Intent.REFUND),
    EvalCase("包裹现在在哪儿", Intent.SHIPPING),
    EvalCase("这个耳机防水吗", Intent.PRODUCT_QA),
    EvalCase("电池能用多久", Intent.PRODUCT_QA),
    EvalCase("你们的服务态度让我很失望", Intent.COMPLAINT),
    EvalCase("打 12315 有用吗", Intent.COMPLAINT),
    # --- 含多个关键词，规则会冲突（规则层会主动放弃，交给模型）---
    EvalCase("我要退货但是物流信息也不更新", Intent.REFUND),
    EvalCase("收到货了想退", Intent.REFUND),
    # --- 模糊 ---
    EvalCase("那个东西有点问题", Intent.UNKNOWN),
    EvalCase("在吗在吗", Intent.CHITCHAT),
    EvalCase("能不能便宜点", Intent.PRODUCT_QA),
    EvalCase("差评", Intent.COMPLAINT),
    EvalCase("我上周买的那笔订单", Intent.UNKNOWN),
]


# ---------------------------------------------------------------- 虚拟模型

# 两个层级的「能力与价格」假设（真实值请自己用 demo_router_llm.py 测）
SMALL = {"accuracy": 0.80, "usd_per_call": 0.00008}
LARGE = {"accuracy": 0.95, "usd_per_call": 0.00060}


class MockLLM:
    """模拟模型：按"能力等级"决定正确率。

    accuracy 参数的意义：模拟"小模型不如大模型"。
    这是分级的核心假设——如果小模型和大模型一样准，就没必要分级。
    """

    def __init__(self, kind: str, accuracy: float, usd_per_call: float) -> None:
        self.kind = kind
        self.accuracy = accuracy
        self.usd_per_call = usd_per_call
        self.calls = 0
        self.random = random.Random(42)

    def invoke(self, prompt: str):
        self.calls += 1
        # 从 prompt 里找出用户消息，用来判断"会不会答对"
        text = prompt.split("用户消息：")[-1].strip()
        truth = _truth_of(text)

        class Msg:
            content = ""

        m = Msg()
        if self.random.random() < self.accuracy:
            m.content = f'{{"intent": "{truth.value}", "confidence": 0.85, "reason": "mock"}}'
        else:
            wrong = self.random.choice([i for i in Intent if i != truth])
            conf = self.random.choice([0.45, 0.55, 0.7])
            m.content = f'{{"intent": "{wrong.value}", "confidence": {conf}, "reason": "mock-wrong"}}'
        return m


def _truth_of(text: str) -> Intent:
    for c in CASES:
        if c.text == text:
            return c.expected
    return Intent.UNKNOWN


# ---------------------------------------------------------------- 三种方案

def plan_a_large_only() -> dict:
    """方案 A：全部用大模型（假设其准确率就是 large_acc）。"""
    return {"accuracy": LARGE["accuracy"], "cost": len(CASES) * LARGE["usd_per_call"],
            "calls": len(CASES), "level_mix": {"large": len(CASES)}}


def plan_b_rules_only() -> dict:
    """方案 B：全部用规则，未命中就 fallback。"""
    correct = sum(1 for c in CASES if (r := rule_classify(c.text)) and r.intent == c.expected)
    return {"accuracy": correct / len(CASES), "cost": 0.0, "calls": 0, "level_mix": {"rule": len(CASES)}}


def plan_c_layered() -> dict:
    """方案 C：三级路由。

    注意：每次方案都要用**全新的** mock 模型，否则 calls 计数会互相污染
    —— 这是对照实验里最容易犯的错（我第一次就踩了）。
    """
    small_llm = MockLLM("small", accuracy=SMALL["accuracy"], usd_per_call=SMALL["usd_per_call"])
    large_llm = MockLLM("large", accuracy=LARGE["accuracy"], usd_per_call=LARGE["usd_per_call"])
    router = IntentRouter(small_llm=small_llm, large_llm=large_llm, threshold=0.6)
    res = evaluate(router, CASES)
    cost = small_llm.calls * small_llm.usd_per_call + large_llm.calls * large_llm.usd_per_call
    return {
        "accuracy": res["accuracy"],
        "cost": cost,
        "calls": small_llm.calls + large_llm.calls,
        "level_mix": res["cost_profile"],
        "errors": res["errors"],
    }

def _llm_call(llm, text: str, level: str) -> IntentResult:
    from common.intent import llm_classify

    return llm_classify(llm, text, cheap=(level == "small"))


# ---------------------------------------------------------------- 主流程

def main() -> None:
    results = {
        "A 全用大模型": plan_a_large_only(),
        "B 全用规则": plan_b_rules_only(),
        "C 三级路由": plan_c_layered(),
    }

    print(f"{len(CASES)} 条测试样本\n")
    print(f"{'方案':<16}{'准确率':>8}{'成本(¥)':>12}{'调用次数':>10}   层级分布")
    print("-" * 82)
    for name, r in results.items():
        mix = ", ".join(f"{k}:{v}" for k, v in r["level_mix"].items() if v)
        print(f"{name:<16}{r['accuracy']:>7.0%}{r['cost'] * 7.2:>12.4f}{r['calls']:>10}   {mix}")

    print("\n" + "=" * 82)
    print("读法")
    print("=" * 82)
    a, b, c = results["A 全用大模型"], results["B 全用规则"], results["C 三级路由"]
    print(f"  · 规则层覆盖了 {c['level_mix'].get('rule', 0)}/{len(CASES)} 条 → 这部分零成本")
    print(f"  · 相比全用大模型，三级路由省了 {(1 - c['cost'] / a['cost']):.0%} 的成本，")
    print(f"    准确率从 {a['accuracy']:.0%} 变为 {c['accuracy']:.0%}")
    print(f"  · 全用规则只有 {b['accuracy']:.0%} —— 便宜但不可用")

    print("\n" + "=" * 82)
    print("三级路由的错误（交给模型分类时出错的样本）")
    print("=" * 82)
    for text, exp, got, level in c["errors"][:6]:
        print(f"  [{level:<5}] {text:<24} 期望={exp:<10} 实际={got}")

    print("\n" + "=" * 82)
    print("关键设计原则")
    print("=" * 82)
    print("  1. 规则层主动放弃：多个关键词命中不同意图时**不下判断**，交给模型")
    print("     —— 这条规则能显著减少'规则误判'这一类最难查的故障")
    print("  2. 阈值 0.6：低于就升级。宁可多花一点，也不要用低置信度的判断走错流程")
    print("  3. 意图 → 路由的映射是**显式表**，不是模型自由发挥（第 5 章的原则）")
    print("\n  ⚠️ 这里的模型准确率是假设值。请用 demo_router_llm.py 在你的真实数据上测。")


if __name__ == "__main__":
    main()




