"""第 4 章 step2：Workflow 还是 Agent——用数字决定，不靠感觉（离线）。

运行：
    python code/ch04_choice/step2_workflow_or_agent.py

上一级的痛点（step1）：诊断出"缺流程"了，但下一步有两条路：
                     Workflow（固定步骤）还是 Agent（动态决策）？
                     你凭感觉选了 Agent，结果它更慢、更贵、更不可控。

这一级做什么：把"步骤确定性"量化成一个分数，然后用同一个任务跑两种实现，
             给出成本、延迟、成功率、可复现性四个数字——选哪个一目了然。

口径来自真实的工程对比（第 19 章会实测 Agent 成本是 Workflow 的 1.88 倍）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Task:
    name: str
    steps: list[str]  # 固定步骤
    branch_points: int  # 需要临场决策的分支数
    tool_calls: int  # 需要的工具调用数


TASKS = [
    Task("退换货判定", ["查订单", "查政策", "判定", "写工单"], branch_points=0, tool_calls=3),
    Task("电商问数", ["召回表结构", "生成 SQL", "校验 SQL", "执行"], branch_points=1, tool_calls=3),
    Task("深度研搜", ["拆解问题", "多轮检索", "交叉验证", "成文"], branch_points=4, tool_calls=12),
    Task("合同审查", ["解析条款", "匹配法条", "标风险", "出报告"], branch_points=2, tool_calls=6),
]


def determinism_score(t: Task) -> float:
    """步骤确定性 0~1：分支越少、步骤越固定，确定性越高。

    公式：1 / (1 + 分支数 × 0.6) —— 每多一个真正的分支，确定性掉一截。
    """
    return 1 / (1 + t.branch_points * 0.6)


# ---- 两种实现的成本模型 -----------------------------------------------------
# 单位：token 与 秒。数字取自同类任务的实测均值（第 2、18、37 章口径）。
LLM_CALL_TOKENS = 1_200  # 一次模型调用的平均 token
LLM_CALL_SECONDS = 1.4


def run_workflow(t: Task) -> dict[str, float]:
    """Workflow：每步一次固定调用，分支用代码写死。"""
    calls = len(t.steps)
    tokens = calls * LLM_CALL_TOKENS
    seconds = calls * LLM_CALL_SECONDS
    # 固定流程的可复现性是 100%，但**分支必须提前写死**——
    # 分支点超过 2 个时，写死的路线会覆盖不到真实情况，成功率随之下降
    success = 0.96 if t.branch_points <= 2 else 0.96 - (t.branch_points - 2) * 0.11
    return {
        "calls": calls,
        "tokens": tokens,
        "seconds": seconds,
        "success": max(0.3, success),
        "reproducible": 1.0,
    }


def run_agent(t: Task, seed: int = 0) -> dict[str, float]:
    """Agent：每步都要模型"想一想"，还要额外决定下一步做什么。

    关键区别：**分支越多，Agent 的优势越大**——因为它能临场决定，
    而 Workflow 只能用提前写死的路线硬套。
    """
    rng = random.Random(seed)
    calls = len(t.steps) + round(t.branch_points * 2.2) + 2
    token_overhead = 1 + t.tool_calls * 0.18
    tokens = calls * LLM_CALL_TOKENS * token_overhead
    seconds = calls * LLM_CALL_SECONDS * 1.15
    # 基础成功率随调用数衰减；但每个分支点给它 +6% 的"应对能力"补回来
    base = 0.97 ** (calls * 0.55)
    bonus = min(0.30, t.branch_points * 0.06)
    success = min(0.97, base + bonus)
    reproducible = max(0.3, 1 - t.branch_points * 0.18 - rng.uniform(0, 0.05))
    return {
        "calls": calls,
        "tokens": tokens,
        "seconds": seconds,
        "success": success,
        "reproducible": reproducible,
    }


def main() -> None:
    print("=" * 96)
    print("第一步：给每个任务算「步骤确定性」")
    print("=" * 96)
    print(f"{'任务':<14}{'固定步骤':>9}{'分支点':>7}{'工具调用':>9}{'确定性':>9}   判断")
    print("-" * 96)
    for t in TASKS:
        s = determinism_score(t)
        verdict = "Workflow 足够" if s >= 0.7 else ("混合（固定骨架 + 局部 Agent）" if s >= 0.45 else "才需要 Agent")
        print(f"{t.name:<14}{len(t.steps):>9}{t.branch_points:>7}{t.tool_calls:>9}{s:>9.2f}   {verdict}")
    print("-" * 96)

    print("\n" + "=" * 96)
    print("第二步：同一任务，两种实现的四个数字")
    print("=" * 96)
    print(f"{'任务':<12}{'实现':<10}{'调用':>5}{'token':>8}{'耗时(s)':>9}{'成功率':>8}{'可复现':>8}")
    print("-" * 96)
    ratios = {}
    for t in TASKS:
        w = run_workflow(t)
        a = run_agent(t)
        ratios[t.name] = (a["tokens"] / w["tokens"], a["seconds"] / w["seconds"], a["success"], w["success"])
        for label, r in (("Workflow", w), ("Agent", a)):
            print(
                f"{t.name if label == 'Workflow' else '':<12}{label:<10}{r['calls']:>5}"
                f"{r['tokens']:>8,.0f}{r['seconds']:>9.1f}{r['success']:>8.0%}{r['reproducible']:>8.0%}"
            )
        print()
    print("-" * 96)

    print("=" * 96)
    print("第三步：Agent 相对 Workflow 的代价")
    print("=" * 96)
    print(f"{'任务':<14}{'token 倍数':>11}{'耗时倍数':>10}{'成功率差':>10}   值得吗")
    print("-" * 96)
    for name, (tk, sec, sa, sw) in ratios.items():
        if sa > sw + 0.10:
            worth = "✅ 值（Agent 换来 +10% 以上成功率）"
        elif sa >= sw - 0.05:
            worth = "🟡 勉强（质量持平，但贵 2~3 倍）"
        else:
            worth = "❌ 不值（Agent 没换来质量）"
        print(f"{name:<14}{tk:>10.2f}x{sec:>9.2f}x{sa - sw:>+10.0%}   {worth}")
    print("-" * 96)

    print("\n" + "=" * 96)
    print("第四步：判断规则（背下来这四条）")
    print("=" * 96)
    rules = [
        ("步骤能提前写死", "→ Workflow", "「查订单→查政策→判定→写工单」永远是这四步"),
        ("分支点 ≤ 1", "→ Workflow + 一个条件判断", "「如果 SQL 校验失败就重写一次」——这是个 if，不是 Agent"),
        ("分支点 2–3，但骨架固定", "→ 混合", "固定部分用 Workflow，局部（比如'怎么查'）交给 Agent"),
        ("分支点 ≥ 4，路线无法预判", "→ Agent", "深度研搜：搜到什么才知道下一步搜什么"),
    ]
    print(f"{'特征':<24}{'结论':<26}例子")
    print("-" * 96)
    for feat, concl, example in rules:
        print(f"{feat:<24}{concl:<26}{example}")
    print("-" * 96)

    print("\n" + "=" * 96)
    print("结论")
    print("=" * 96)
    print("  · **先问'步骤能不能提前写死'，而不是'要不要用 Agent'。**")
    print("  · Agent 的代价是实打实的：token ×2~3、耗时 ×2、可复现性下降到 50–70%。")
    print("    换来的是「能做 Workflow 写不出来的事」，不是「做得更好」。")
    print("  · 真实系统几乎都是混合的：**固定骨架用 Workflow，需要临场判断的节点用 Agent。**")
    print("    第 19 章会把这个混合形态写出来。")
    print()
    print("  一句话判据：")
    print("    「如果我把流程图画出来，分支能有几条？」")
    print("      ≤ 2 条 → Workflow")
    print("      3–5 条 → 混合")
    print("      > 5 条或画不出来 → Agent")

    assert ratios["退换货判定"][0] > 1, "Agent 必须比 Workflow 贵"


if __name__ == "__main__":
    main()
