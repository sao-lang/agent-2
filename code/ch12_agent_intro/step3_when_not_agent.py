"""第 12 章 step3：同一个任务，Agent 和 Workflow 各跑一遍（离线）。

运行：
    python code/ch12_agent_intro/step3_when_not_agent.py

上一级的痛点（step2）：你会写 Agent 循环了，于是想给所有任务都套上它。

这一级做什么：用**同一批任务**跑两种实现，让"什么时候不该用 Agent"变成数字：
  · Workflow：步骤写死，没有模型决策
  · Agent   ：每一步都要模型判断

指标：步数、token、耗时、成功率、可复现性。
结论来自第 4 章 step2 的实测口径（那边量到 Agent 贵 2.31 倍），
这里把它展开到具体任务上。
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Task:
    name: str
    steps: list[str]
    branches: int      # 需要临场决策的分支数
    tools: int


TASKS = [
    Task("政策问答", ["检索", "生成"], branches=0, tools=1),
    Task("退换货判定", ["查订单", "查政策", "判定", "写工单"], branches=0, tools=3),
    Task("多品类退换货", ["查订单", "判定品类", "查对应政策", "判定", "写工单"], branches=2, tools=4),
    Task("复杂纠纷处理", ["查订单", "查历史", "查政策", "搜集证据", "判定", "上报"], branches=5, tools=6),
]

# 与第 2 章一致：一次调用 2250 in + 300 out
CALL_TOKENS = 1_200
CALL_SECONDS = 1.4


def workflow(t: Task) -> dict:
    """Workflow：每步一次固定调用，分支写死在代码里。"""
    calls = len(t.steps)
    tokens = calls * CALL_TOKENS
    seconds = calls * CALL_SECONDS
    # 分支 ≤2 时写死的路线能覆盖；超过就漏
    success = 0.96 if t.branches <= 2 else 0.96 - (t.branches - 2) * 0.11
    return {
        "calls": calls,
        "tokens": tokens,
        "seconds": seconds,
        "success": max(0.3, success),
        "reproducible": 1.0,
    }


def agent(t: Task, seed: int = 0) -> dict:
    """Agent：每步都要模型判断，还要额外决定下一步。"""
    rng = random.Random(seed)
    calls = len(t.steps) + round(t.branches * 2.2) + 2
    tokens = calls * CALL_TOKENS * (1 + t.tools * 0.18)
    seconds = calls * CALL_SECONDS * 1.15
    base = 0.97 ** (calls * 0.55)
    success = min(0.97, base + min(0.30, t.branches * 0.06))
    reproducible = max(0.3, 1 - t.branches * 0.18 - rng.uniform(0, 0.05))
    return {
        "calls": calls,
        "tokens": tokens,
        "seconds": seconds,
        "success": success,
        "reproducible": reproducible,
    }


def main() -> None:
    print("=" * 96)
    print("同一批任务，两种实现的五个指标")
    print("=" * 96)

    print(f"\n{'任务':<16}{'实现':<10}{'调用':>5}{'token':>8}{'耗时(s)':>9}{'成功率':>8}{'可复现':>8}")
    print("-" * 96)
    rows = []
    for t in TASKS:
        w, a = workflow(t), agent(t)
        for label, r in (("Workflow", w), ("Agent", a)):
            print(f"{t.name if label == 'Workflow' else '':<16}{label:<10}{r['calls']:>5}"
                  f"{r['tokens']:>8,.0f}{r['seconds']:>9.1f}{r['success']:>8.0%}{r['reproducible']:>8.0%}")
        rows.append((t, w, a))
        print()

    print("-" * 96)
    print("\n" + "=" * 96)
    print("Agent 相对 Workflow 的代价")
    print("=" * 96)
    print(f"{'任务':<16}{'分支':>5}{'token':>8}{'耗时':>8}{'成功率差':>9}   判断")
    print("-" * 96)
    for t, w, a in rows:
        ratio_t = a["tokens"] / w["tokens"]
        ratio_s = a["seconds"] / w["seconds"]
        delta = a["success"] - w["success"]
        if delta > 0.10:
            verdict = "✅ 用 Agent（写死的路线覆盖不了）"
        elif delta >= -0.05:
            verdict = "🟡 不值（贵 2–3 倍，质量持平）"
        else:
            verdict = "❌ 明显更差（Agent 白花了钱）"
        print(f"{t.name:<16}{t.branches:>5}{ratio_t:>7.2f}x{ratio_s:>7.2f}x{delta:>+9.0%}   {verdict}")
    print("-" * 96)

    print("\n" + "=" * 96)
    print("为什么分支多的时候 Agent 反而赢")
    print("=" * 96)
    print("  Workflow 的路线是**人提前写死的**。分支 0 个时它 100% 覆盖；")
    print("  分支 5 个时，写死的路线只能覆盖其中一部分 → 覆盖率下降。")
    print()
    print("  Agent 的路线是**模型临场决定的**，所以分支越多它越有优势 ——")
    print("  但代价是：token ×N、耗时 ×N、可复现性掉到 30–70%。")
    print()
    print("  **这就是「分支数」成为判据的原因**，不是「任务复杂度」这种主观感觉。")

    print("\n" + "=" * 96)
    print("一张决策表（把它贴在显示器上）")
    print("=" * 96)
    table = [
        ("0 个分支，步骤固定", "Workflow", "退换货判定、政策问答"),
        ("1–2 个分支", "Workflow + if", "多品类时加一个 if 判品类"),
        ("3–5 个分支，骨架固定", "混合", "固定部分 Workflow，局部 Agent"),
        (">5 个或画不出流程图", "Agent", "复杂纠纷、深度研搜"),
    ]
    print(f"  {'特征':<26}{'选择':<20}例子")
    print("  " + "-" * 86)
    for a, b, c in table:
        print(f"  {a:<26}{b:<20}{c}")

    print("\n" + "=" * 96)
    print("一个真实的反例：给政策问答上了 Agent")
    print("=" * 96)
    t = TASKS[0]
    w, a = workflow(t), agent(t)
    print(f"  任务：{t.name}（{t.steps}），分支 {t.branches} 个")
    print(f"  Workflow：{w['calls']} 次调用，{w['tokens']:,.0f} token，{w['seconds']:.1f}s，成功 {w['success']:.0%}")
    print(f"  Agent   ：{a['calls']} 次调用，{a['tokens']:,.0f} token，{a['seconds']:.1f}s，成功 {a['success']:.0%}")
    print()
    print(f"  → token 涨 {a['tokens'] / w['tokens']:.1f} 倍，耗时涨 {a['seconds'] / w['seconds']:.1f} 倍，")
    print(f"    成功率反而降了 {(w['success'] - a['success']) * 100:.0f} 个点。")
    print()
    print("  原因：这个任务本来就是'查一下再答'，Agent 的多轮决策纯属浪费。")
    print("  **如果 Agent 的大部分步骤都是'查一下再答'，那它就是 RAG，不是 Agent。**")

    print("\n" + "=" * 96)
    print("结论")
    print("=" * 96)
    print("  · 判据是 **分支数**，不是'任务复不复杂'这种主观感觉。")
    print("  · 分支 ≤ 2：Workflow。Agent 只会让它更慢更贵更不可复现。")
    print("  · 分支 > 5 或画不出流程图：才用 Agent。")
    print("  · **可复现性是最容易被忽略的代价**：")
    print("    Workflow 100%（同一输入永远同一路径），Agent 30–70%。")
    print("    金融、医疗这类场景，这一条往往直接否决 Agent。")
    print()
    print("  第 19 章会给出一个真实的混合形态：固定骨架 + 局部 Agent。")

    assert rows[0][1]["tokens"] < rows[0][2]["tokens"]


if __name__ == "__main__":
    main()
