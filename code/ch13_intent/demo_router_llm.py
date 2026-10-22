"""第 13 章示例 2：在真实模型上测意图识别的准确率与成本（需要 API key）。

运行：
    python code/ch13_intent/demo_router_llm.py
    python code/ch13_intent/demo_router_llm.py --limit 5   # 省钱

它会做两件事：
  1. 用「便宜模型」和「主模型」分别跑同一批样本，输出准确率与成本
  2. 跑一次三级路由，告诉你"分级设计"在你的数据上能省多少

⚠️ 你一定会遇到这种情况：小模型在某几类意图上明显更差。
   这就是分级设计的边界——**必须用数据找出"哪些意图可以下放"**。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import Meter, get_settings, make_llm  # noqa: E402
from common.intent import IntentRouter, evaluate, llm_classify  # noqa: E402

from demo_router import CASES  # noqa: E402  复用同一批样本


def run_level(llm, meter: Meter, label: str, cases) -> dict:
    correct = 0
    errors = []
    for c in cases:
        with meter.track(get_settings().model, step=f"intent-{label}") as rec:
            r = llm_classify(llm, c.text, cheap=(label == "small"))
            rec.input_tokens = 300    # 粗略估算；精确值请从 usage_of(msg) 取
            rec.output_tokens = 40
        if r.intent == c.expected:
            correct += 1
        else:
            errors.append((c.text, c.expected.value, r.intent.value, r.confidence))
    return {"accuracy": correct / max(len(cases), 1), "errors": errors}


def main() -> None:
    s = get_settings()
    if s.api_key in ("missing", ""):
        print("❌ 需要 API key。请复制 .env-example 为 .env 并填入配置。")
        print("   如果只想看方法，请用：python code/ch13_intent/demo_router.py（离线，用虚拟模型）")
        return

    cases = CASES
    if "--limit" in sys.argv:
        cases = CASES[: int(sys.argv[sys.argv.index("--limit") + 1])]

    small = make_llm(model=s.cheap_model)
    large = make_llm(model=s.model)

    print("=" * 74)
    print("① 单层对比：便宜模型 vs 主模型")
    print("=" * 74)

    for label, llm in [("small", small), ("large", large)]:
        meter = Meter()
        res = run_level(llm, meter, label, cases)
        summary = meter.summary()
        print(f"\n[{label}] {s.cheap_model if label == 'small' else s.model}")
        print(f"  准确率：{res['accuracy']:.0%}   成本：¥{summary['cost']:.4f}（{summary['calls']} 次）")
        if res["errors"]:
            print("  错误：")
            for text, exp, got, conf in res["errors"][:5]:
                print(f"    {text[:22]:<24} 期望={exp:<10} 实际={got:<10} conf={conf:.2f}")

    print("\n" + "=" * 74)
    print("② 三级路由：规则 → 便宜模型 → 主模型")
    print("=" * 74)
    router = IntentRouter(small_llm=small, large_llm=large, threshold=0.6)
    res = evaluate(router, cases)
    print(f"  准确率：{res['accuracy']:.0%}")
    print(f"  层级分布：{res['cost_profile']}")

    print("\n" + "=" * 74)
    print("③ 该往哪优化")
    print("=" * 74)
    print("  · 规则层错 → 加关键词（最便宜）")
    print("  · 便宜模型错、主模型对 → 这类意图**不要下放**（写进规则或强制升级）")
    print("  · 两个都错 → 意图定义有问题（可能该拆出更细的意图）")
    print("\n  请把上面的错误列表按意图归类，产出一张")
    print("  「意图 × 可下放层级」的表格——这就是你的路由策略依据。")


if __name__ == "__main__":
    main()
