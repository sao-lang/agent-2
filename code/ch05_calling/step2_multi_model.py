"""第 5 章 step2：多模型路由与降级——为什么"直接换便宜的"会翻车（离线）。

运行：
    python code/ch05_calling/step2_multi_model.py

上一级的痛点（step1）：一次调用会了。但线上你会遇到三种情况：
                     ① 贵模型太烧钱，想给简单问题换便宜模型
                     ② 便宜模型答不了复杂问题
                     ③ 主模型挂了（限流/超时），不能整个服务跟着挂

这一级做什么：跑 12 条真实问题，对比三种策略的成本与质量：
  A. 全用贵模型（基线）
  B. 全用便宜模型
  C. **按难度路由**：先用规则+小模型打分，简单走便宜、复杂走贵
  D. **主备降级**：贵模型失败时自动退到便宜模型（保命，不是省钱）

核心结论：路由能省 40–60% 成本，但**必须有质量守门**——
         否则你省下的钱会在客服投诉里加倍还回去。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.meter import price_of  # noqa: E402

# ---- 两个模型 ---------------------------------------------------------------
STRONG = "deepseek-chat"     # 2.0 / 8.0 元每百万
CHEAP = "qwen-plus"          # 0.8 / 2.0 元每百万


@dataclass
class Q:
    text: str
    difficulty: int  # 1=简单 2=中等 3=复杂
    need_strong: bool  # 便宜模型能否答对


QUESTIONS = [
    Q("退货要几天？", 1, False),
    Q("运费谁出？", 1, False),
    Q("优惠券会退吗？", 1, False),
    Q("怎么申请售后？", 1, False),
    Q("耳机能退吗？", 2, False),
    Q("我这个用了三天坏了能换吗？", 2, False),
    Q("满减凑单退货后优惠怎么算？", 2, True),
    Q("定制商品拆封了还能退吗？", 2, False),
    Q("三次换货都不行，我能要求全额退款加赔偿吗？", 3, True),
    Q("我这个订单里有两件商品，一件退一件留，运费和券怎么分摊？", 3, True),
    Q("你们这个政策符不符合消费者权益保护法第二十四条？", 3, True),
    Q("帮我比较一下无理由退货和质保换新的区别和适用场景", 3, True),
]

# 每次调用的 token（第 2 章口径）
IN_TOKENS = 2_250
OUT_TOKENS = 300
CALLS_PER_DAY = 1_000


def cost(model: str) -> float:
    pin, pout = price_of(model)
    return IN_TOKENS / 1e6 * pin + OUT_TOKENS / 1e6 * pout


def run(strategy: str) -> dict[str, float]:
    """返回 {总成本, 答对率, 调用次数}。成本按 12 条问题算，然后折算到每天。"""
    total = 0.0
    correct = 0
    calls = 0

    for q in QUESTIONS:
        if strategy == "全用强模型":
            total += cost(STRONG)
            correct += 1  # 强模型全对
            calls += 1
        elif strategy == "全用便宜模型":
            total += cost(CHEAP)
            correct += 0 if q.need_strong else 1
            calls += 1
        elif strategy == "按难度路由":
            # 规则打分：短、无数字、无"比较/分摊/法律"等关键词 → 便宜
            simple = q.difficulty == 1 or (q.difficulty == 2 and len(q.text) < 20)
            m = CHEAP if simple else STRONG
            total += cost(m)
            # 路由承诺：简单问题便宜模型能答对；复杂问题走强模型
            if simple:
                correct += 0 if q.need_strong else 1
            else:
                correct += 1
            calls += 1
        elif strategy == "路由 + 主备降级":
            simple = q.difficulty == 1 or (q.difficulty == 2 and len(q.text) < 20)
            m = CHEAP if simple else STRONG
            total += cost(m)
            calls += 1
            if simple:
                correct += 0 if q.need_strong else 1
            else:
                correct += 1
            # 降级只在"主模型失败"时生效，这里 12 条都成功，所以不额外计费
    return {"cost": total, "accuracy": correct / len(QUESTIONS), "calls": calls}


def main() -> None:
    n = len(QUESTIONS)
    print("=" * 88)
    print(f"{n} 条真实客服问题，四种策略对比")
    print("=" * 88)
    print(f"强模型 {STRONG}：{cost(STRONG):.6f} 元/次")
    print(f"便宜模型 {CHEAP}：{cost(CHEAP):.6f} 元/次")
    print(f"便宜/强的单次成本比：{cost(CHEAP) / cost(STRONG):.0%}\n")

    strategies = ["全用强模型", "全用便宜模型", "按难度路由", "路由 + 主备降级"]
    results = {}
    print(f"{'策略':<20}{'12条成本':>12}{'答对率':>9}{'日均成本':>12}   说明")
    print("-" * 88)
    notes = {
        "全用强模型": "最稳，最贵",
        "全用便宜模型": "最省，但复杂问题答错",
        "按难度路由": "成本大降，但路由判错就答错",
        "路由 + 主备降级": "成本同路由，且主模型挂了不宕机",
    }
    for s in strategies:
        r = run(s)
        results[s] = r
        daily = r["cost"] / n * CALLS_PER_DAY
        print(f"{s:<20}{r['cost']:>12.6f}{r['accuracy']:>9.0%}{daily:>12.2f}   {notes[s]}")
    print("-" * 88)

    base = results["全用强模型"]
    print("\n" + "=" * 88)
    print("相对「全用强模型」的变化")
    print("=" * 88)
    print(f"{'策略':<20}{'成本':>10}{'答对率':>10}   值不值")
    print("-" * 88)
    for s in strategies[1:]:
        r = results[s]
        dc = r["cost"] / base["cost"] - 1
        da = r["accuracy"] - base["accuracy"]
        if da < -0.01:
            worth = f"❌ 省了 {-dc:.0%} 成本，但答错率 +{-da:.0%}"
        elif dc < -0.3:
            worth = f"✅ 省 {-dc:.0%} 成本，质量不掉"
        else:
            worth = "🟡 收益不明显"
        print(f"{s:<20}{dc:>+9.0%}{da:>+10.0%}   {worth}")
    print("-" * 88)

    print("\n" + "=" * 88)
    print("路由判错的代价（这是最容易被忽略的）")
    print("=" * 88)
    wrong = [q for q in QUESTIONS if q.need_strong and q.difficulty == 2]
    print(f"  有 {len(wrong)} 条「中等难度但便宜模型答不对」的问题：")
    for q in wrong:
        print(f"    · {q.text}")
    print()
    print("  如果路由规则只看「文本长度 < 20」，有一条就会被错判：")
    print(f"    「{wrong[0].text}」 长度 {len(wrong[0].text)} < 20 → 路由到便宜模型 → 答错")
    print()
    print("  **所以路由不能只靠长度。** 可靠的规则是：")
    print("    ① 命中'比较/分摊/法律/赔偿'等复杂词 → 强模型")
    print("    ② 含 2 个以上子问题（'并且''还有''同时'）→ 强模型")
    print("    ③ 其余 → 便宜模型")
    print("    ④ **每次路由都记日志**，抽 5% 人工复核，发现判错就改规则")

    print("\n" + "=" * 88)
    print("四种策略各自适合什么")
    print("=" * 88)
    table = [
        ("全用强模型", "量小（<1000/天）、质量第一", "不要为了省钱牺牲质量"),
        ("全用便宜模型", "任务极简单（分类、抽取）", "稍复杂就答错"),
        ("按难度路由", "量大、问题难度分布明显", "必须配质量守门"),
        ("主备降级", "任何线上服务", "**这是保命，不是省钱**"),
    ]
    print(f"  {'策略':<18}{'适合':<28}注意")
    print("  " + "-" * 78)
    for a, b, c in table:
        print(f"  {a:<18}{b:<28}{c}")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  · 路由的价值是**真实的**：成本能降 40–60%，前提是规则判得准。")
    print("  · 难点不是「怎么省」，是「**怎么知道这次不该省**」。所以必须配三样：")
    print("      ① 可判定的难度规则（不是长度）")
    print("      ② 路由决策日志（第 40 章 trace）")
    print("      ③ 抽样复核（第 44 章评测）")
    print("  · **主备降级是另一件事**：它不省钱，它防宕机。")
    print("    主模型 429/超时 → 自动切备用，宁可答案差一点也不要 500。")

    assert results["按难度路由"]["cost"] < results["全用强模型"]["cost"]


if __name__ == "__main__":
    main()

