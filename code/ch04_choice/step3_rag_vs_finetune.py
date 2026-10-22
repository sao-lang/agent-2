"""第 4 章 step3：RAG 还是微调——用三年总成本说话（离线）。

运行：
    python code/ch04_choice/step3_rag_vs_finetune.py

上一级的痛点（step2）：流程选完了。但"内部知识问答"这类任务还有两条路：
                     RAG（检索）和微调（改参数）。很多人凭"微调听起来更专业"就选了后者。

这一级做什么：把两条路的**首年成本 + 三年总成本**算出来，并标出各自的能力边界。

关键不是哪个"更先进"，而是：
  · RAG 改的是**上下文**，微调改的是**参数**
  · 知识会变 → RAG 赢；行为要稳 → 微调赢
  · 两者可以叠加，但不要一开始就叠
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Plan:
    name: str
    setup_days: int          # 一次性建设人天
    update_days: int         # 每次知识/行为更新的人天
    updates_per_year: int    # 一年更新几次
    train_cost: float        # 每次训练的钱（元），RAG 为 0
    inference_multiplier: float  # 推理成本倍率（相对裸调用）
    can_cite: bool           # 能否给出来源引用
    can_change_behavior: bool  # 能否改变输出风格/格式稳定性
    knows_new: bool          # 新知识当天生效


DAY_RATE = 1_500.0  # 一个人天按 1500 元算（含社保与管理摊销）

PLANS = [
    Plan("裸调用（基线）", 1, 0, 0, 0, 1.0, False, False, False),
    Plan("Prompt + 结构化输出", 3, 0.5, 4, 0, 1.15, False, True, False),
    Plan("RAG", 15, 1, 12, 0, 1.6, True, False, True),
    Plan("微调（LoRA）", 25, 8, 4, 3_000, 1.0, False, True, False),
    Plan("RAG + 微调", 38, 9, 12, 3_000, 1.6, True, True, True),
]

# 一次问答的基线成本（元/次），来自第 2 章的口径
BASE_COST_PER_CALL = 0.0069
CALLS_PER_YEAR = 300 * 1_000  # 每天 1000 次 × 300 天


def yearly_cost(p: Plan, year: int) -> dict[str, float]:
    """第 year 年的总成本。"""
    build = (p.setup_days if year == 1 else 0) * DAY_RATE
    maintain = p.update_days * p.updates_per_year * DAY_RATE
    train = p.train_cost * p.updates_per_year if year > 1 or p.setup_days > 0 else 0
    if p.name == "裸调用（基线）":
        train = 0
    infer = BASE_COST_PER_CALL * p.inference_multiplier * CALLS_PER_YEAR
    return {"build": build, "maintain": maintain, "train": train, "infer": infer,
            "total": build + maintain + train + infer}


def main() -> None:
    print("=" * 96)
    print("口径")
    print("=" * 96)
    print(f"  人天单价：¥{DAY_RATE:,.0f}")
    print(f"  调用量：{CALLS_PER_YEAR:,} 次/年（每天 1000 次 × 300 天）")
    print(f"  单次基线成本：¥{BASE_COST_PER_CALL}（第 2 章：2250 in + 300 out）")

    print("\n" + "=" * 96)
    print("第一年成本明细")
    print("=" * 96)
    print(f"{'方案':<20}{'建设':>12}{'维护':>11}{'训练':>10}{'推理':>12}{'合计':>13}")
    print("-" * 96)
    first = {}
    for p in PLANS:
        y = yearly_cost(p, 1)
        first[p.name] = y
        print(f"{p.name:<20}¥{y['build']:>11,.0f}¥{y['maintain']:>10,.0f}¥{y['train']:>9,.0f}¥{y['infer']:>11,.0f}¥{y['total']:>12,.0f}")
    print("-" * 96)

    print("\n" + "=" * 96)
    print("三年总成本")
    print("=" * 96)
    print(f"{'方案':<20}{'第1年':>13}{'第2年':>13}{'第3年':>13}{'三年合计':>14}{'相对基线':>10}")
    print("-" * 96)
    base3 = sum(yearly_cost(PLANS[0], y)["total"] for y in (1, 2, 3))
    for p in PLANS:
        ys = [yearly_cost(p, y)["total"] for y in (1, 2, 3)]
        total3 = sum(ys)
        print(
            f"{p.name:<20}¥{ys[0]:>12,.0f}¥{ys[1]:>12,.0f}¥{ys[2]:>12,.0f}"
            f"¥{total3:>13,.0f}{total3 / base3:>9.2f}x"
        )
    print("-" * 96)

    print("\n" + "=" * 96)
    print("能力对照（成本之外，这才是决策的真正依据）")
    print("=" * 96)
    print(f"{'方案':<20}{'可引用来源':>11}{'改行为':>8}{'新知识当天生效':>14}   最适合")
    print("-" * 96)
    fit = {
        "裸调用（基线）": "通用问答",
        "Prompt + 结构化输出": "格式要求高的抽取",
        "RAG": "内部制度、产品手册、FAQ",
        "微调（LoRA）": "固定话术、分类口径、风格统一",
        "RAG + 微调": "既要查资料、又要严格格式",
    }
    for p in PLANS:
        print(
            f"{p.name:<20}{'✅' if p.can_cite else '❌':>10}"
            f"{'✅' if p.can_change_behavior else '❌':>8}"
            f"{'✅' if p.knows_new else '❌':>13}   {fit[p.name]}"
        )
    print("-" * 96)

    print("\n" + "=" * 96)
    print("为什么'内部知识库问答'不该先上微调")
    print("=" * 96)
    rag = first["RAG"]
    ft = first["微调（LoRA）"]
    print(f"  第一年：RAG ¥{rag['total']:,.0f} vs 微调 ¥{ft['total']:,.0f}"
          f"（微调是 RAG 的 {ft['total'] / rag['total']:.1f} 倍）")
    print()
    print("  更关键的是三个'不可接受'：")
    print("    ① 微调**无法给出来源**——制度问答里'依据在哪份文件'是刚需（合规）")
    print("    ② 微调**知识更新要重新训练**——制度每季度改，一年 4 次训练")
    print("    ③ 微调**不能消除幻觉**——它只让输出更像训练数据，不会让它'不知道就说不知道'")
    print()
    print("  这三条里任何一条成立，RAG 就是唯一选择。")

    print("\n" + "=" * 96)
    print("什么时候微调真的划算")
    print("=" * 96)
    print("  · 任务**不需要新知识**（比如固定格式的字段抽取）")
    print("  · 有 **500+ 条高质量标注数据**（低质量数据训出来的更差）")
    print("  · **行为要求极稳**（分类口径必须 100% 一致，prompt 做不到）")
    print("  · 推理量大到**小模型也能顶**（把大模型蒸馏成小模型，省推理费）")
    print()
    print("  最后一条是最容易被忽略的真实价值：**微调不是为了效果，是为了降本。**")
    print("  把 deepseek-chat（2 元/百万）换成微调过的 7B 自部署，推理成本能降 80%。")

    print("\n" + "=" * 96)
    print("结论")
    print("=" * 96)
    print("  · **缺知识 → RAG；缺行为 → 微调。** 这是唯一需要背的一句话。")
    print("  · 成本上，微调第一年是 RAG 的 2.3 倍；三年看差距**不会缩小**——")
    print("    微调每年仍需 4 次重训 + 8 人天数据维护，RAG 每年 12 次更新 × 1 人天。")
    print("  · 但决策不该只看钱：**能否引用来源、知识多久变一次、幻觉是否可接受**，")
    print("    这三条往往直接否决微调。")
    print("  · 两者可以叠加，但**不要一开始就叠**。先用 RAG 跑通，")
    print("    等'格式仍然不稳'成为主要矛盾时，再考虑微调。")

    assert first["微调（LoRA）"]["total"] > first["RAG"]["total"]


if __name__ == "__main__":
    main()
