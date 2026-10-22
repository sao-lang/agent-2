"""第 3 章 step2：Zero-shot vs Few-shot——示例到底补了什么（离线）。

运行：
    python code/ch03_prompt/step2_few_shot.py

上一级的痛点（step1）：六要素都写了，但输出还是飘——
                      "退货"有时归到"售后"，有时归到"物流"。这是**边界**没定义。

这一级做什么：用同一个任务跑三种写法，让"示例"的作用变成可数的数字：
  ① Zero-shot：只给定义
  ② Few-shot（正例）：给 3 个正确示例
  ③ Few-shot（正例 + 负例）：再加 2 个"看起来像但不是"的例子

判定用一个小规则引擎（关键词打分），它模拟"模型会怎么理解你的定义"。
关键不是它准不准，而是**三种写法在同一个判定标准下差多少**。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---- 任务：把客服工单分到 3 个队列 -------------------------------------------
LABELS = ["退款退货", "物流配送", "商品质量"]


@dataclass
class Case:
    text: str
    gold: str
    note: str


# 14 条测试用例，故意包含大量"边界"情况
CASES = [
    Case("我要退款，东西不要了", "退款退货", "明确"),
    Case("申请无理由退货怎么操作", "退款退货", "明确"),
    Case("钱什么时候退给我", "退款退货", "只提退款动作"),
    Case("这个能不能七天无理由", "退款退货", "只提政策"),
    Case("快递三天没动了", "物流配送", "明确"),
    Case("发错地址了能改吗", "物流配送", "明确"),
    Case("什么时候能到", "物流配送", "只问时效"),
    Case("收到的时候箱子是破的", "物流配送", "边界：包装破损 ≠ 商品坏"),
    Case("耳机右耳没声音", "商品质量", "明确"),
    Case("充不进电，用了两天", "商品质量", "明确"),
    Case("屏幕有划痕，一开箱就有", "商品质量", "边界：开箱即损"),
    Case("耳机有滋滋声，我想退货", "商品质量", "边界：既提质量也提退货"),
    Case("收到是坏的，能换一个吗", "商品质量", "边界：提换货"),
    Case("包装破了但东西没坏，能退吗", "物流配送", "边界：主诉是包装，诉求是退"),
]


# ---- 三种写法的"模型理解"----------------------------------------------------


def zero_shot(text: str) -> str:
    """只给定义时的行为：谁的关键词多算谁。

    这模拟真实模型的典型失败模式——**定义里出现过的词，权重被放大**，
    所以"退货"这个词会把质量问题和退款问题都吸到"退款退货"。
    """
    rules = {
        "退款退货": ["退款", "退货", "退", "七天", "无理由", "钱"],
        "物流配送": ["快递", "物流", "地址", "什么时候能到", "到货", "箱子", "包装"],
        "商品质量": ["声音", "坏", "划痕", "充不进", "滋滋", "故障", "不能用"],
    }
    scores = {k: sum(t in text for t in v) for k, v in rules.items()}
    # 关键：定义里"退货"是退款类的核心词，权重 +1.5，会盖过质量词
    scores["退款退货"] += 1.5 * sum(t in text for t in ["退货", "退"])
    return max(scores, key=lambda k: scores[k])


# few-shot 正例：从示例里学到"主诉优先于诉求"
SHOT_POSITIVE = [
    ("耳机右耳没声音，我要退货", "商品质量"),
    ("快递一直不更新", "物流配送"),
    ("不想要了，退款", "退款退货"),
]

# few-shot 负例：明确告诉模型"这两类不要混"
SHOT_NEGATIVE = [
    ("东西坏了我要退货", "商品质量", "虽然提了退货，但主诉是坏了"),
    ("包装破了但东西好好的", "物流配送", "主诉是包装，不是商品"),
]


def few_shot_positive(text: str) -> str:
    """正例的作用：把"主诉优先"这条隐含规则显式化。

    但注意：3 个正例只教会了"有质量词 → 判质量"，
    **没教"什么时候不该这么判"**。所以"包装破了但东西没坏"会被误判。
    """
    if any(t in text for t in ["没声音", "坏", "划痕", "充不进", "滋滋", "故障"]):
        return "商品质量"
    return zero_shot(text)


def few_shot_with_negative(text: str) -> str:
    """加负例的作用：明确"边界不要怎么判"，消除最后一类混淆。

    负例 ("包装破了但东西好好的" → 物流配送) 教会了模型：
    「坏」这个词如果修饰的是包装而不是商品本身，就要走物流。
    """
    # 先判断"坏"修饰的对象：是包装 → 物流；是商品 → 质量
    if "包装" in text and any(t in text for t in ["破", "坏"]):
        if any(t in text for t in ["没坏", "好好的", "没坏东西", "东西没坏"]):
            return "物流配送"
    return few_shot_positive(text)


METHODS = [
    ("① Zero-shot（只给定义）", zero_shot),
    ("② Few-shot（3 个正例）", few_shot_positive),
    ("③ Few-shot（正例 + 负例）", few_shot_with_negative),
]


def evaluate(fn) -> tuple[int, list[tuple[Case, str]]]:
    wrong = [(c, fn(c.text)) for c in CASES if fn(c.text) != c.gold]
    return len(CASES) - len(wrong), wrong


def main() -> None:
    print("=" * 88)
    print(f"同一任务三种写法：{len(CASES)} 条测试用例")
    print("=" * 88)
    print(f"{'写法':<26}{'正确':>6}{'准确率':>9}   错了哪些")
    print("-" * 88)
    results = []
    for name, fn in METHODS:
        right, wrong = evaluate(fn)
        results.append((name, right, wrong))
        sample = "、".join(c.text[:8] for c, _ in wrong[:2]) or "—"
        print(f"{name:<26}{right:>4}/{len(CASES)}{right / len(CASES):>9.0%}   {sample}")
    print("-" * 88)

    print("\n" + "=" * 88)
    print("Zero-shot 错在哪（逐条看）")
    print("=" * 88)
    _, wrong0 = evaluate(zero_shot)
    for c, pred in wrong0:
        print(f"  「{c.text}」")
        print(f"    标准答案：{c.gold}   模型判成：{pred}")
        print(f"    ← {c.note}\n")

    print("=" * 88)
    print("加了负例之后，还剩哪些错")
    print("=" * 88)
    _, wrong2 = evaluate(few_shot_with_negative)
    if not wrong2:
        print("  全部正确。负例把最后一类边界消除掉了。")
    else:
        for c, pred in wrong2:
            print(f"  「{c.text}」→ 判成 {pred}（应为 {c.gold}）   {c.note}")

    print("\n" + "=" * 88)
    print("结论：示例补的到底是什么")
    print("=" * 88)
    print("  · Zero-shot 的失败不是'模型笨'，是**你的定义有歧义**——")
    print("    \"耳机没声音想退货\"里同时有质量词和退货词，定义没说谁优先。")
    print("  · 正例补的是「**隐含规则**」：3 个正例让模型学到'主诉优先于诉求'。")
    print("  · 负例补的是「**边界的反面**」：'提了退货但主诉是坏了 → 判质量'。")
    print("    这类知识**很难用定义写清楚**，但一个反例就够。")
    print()
    print("  所以写法选择的判据是：")
    print("    任务边界清楚 → Zero-shot 就够（省钱、省 token）")
    print("    边界模糊、有隐含规则 → 加正例")
    print("    两类容易混淆 → 必须加负例")
    print()
    print("  ⚠️ 但示例也有代价：每个示例都占 token（第 2 章）。")
    print("     3 正例 + 2 负例 ≈ 250 token ≈ 每次调用多花 10%。")

    best = max(r for _, r, _ in results)
    assert best == len(CASES), "正例+负例应该全对，否则规则引擎写错了"


if __name__ == "__main__":
    main()
