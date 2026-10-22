"""第 19 章 · 第 1 级：为什么 ReAct 在多步任务上会跑偏。

运行：
    python code/ch06_react_vs_plan/step1_react_drift.py

这一级不给方案，只**演示问题**。
同一个任务（调研三家竞品），一个"走一步看一步"的流程会怎么变卦。

注意：这里的假模型是**故意写得"很合理"**的 —— 它不是坏模型，
它只是每次看到的上下文不同，所以每次的"合理判断"也不同。
这正是 ReAct 在长任务上跑偏的机制。
"""
from __future__ import annotations

COMPETITORS = ["竞品A", "竞品B", "竞品C"]


def step1_react_style() -> dict:
    """模拟一次 ReAct：每步只看"到目前为止的历史"，自行决定下一步。"""
    history: list[str] = []
    findings: dict[str, str] = {}
    trace: list[str] = []

    # —— 第 1 步：看到问题是"调研三家竞品"，决定查"价格"
    history.append("用户：调研三家竞品的定价策略")
    trace.append("想：先查价格。搜『竞品A 价格』")
    findings["竞品A"] = "价格 ¥99/月"

    # —— 第 2 步：历史里只有"价格"，继续查价格
    history.append("观察：竞品A 价格 ¥99/月")
    trace.append("想：继续。搜『竞品B 价格』")
    findings["竞品B"] = "价格 ¥129/月"

    # —— 第 3 步：前两条结果里出现了"按席位""按调用量"这些字眼
    #    模型（合理地）意识到：光比价格没意义，要统一计费口径
    history.append("观察：竞品A ¥99/月（按席位）；竞品B ¥129/月（按调用量）")
    trace.append("想：口径不一致，得换维度。搜『竞品C 定价模式』")
    findings["竞品C"] = "定价模式：免费额度 10 万 token"

    # —— 第 4 步：汇总时，前两家只有价格，第三家只有模式
    trace.append("想：可以总结了")
    return {"findings": findings, "trace": trace}


def step1_plan_style() -> dict:
    """同一个任务，换成"先写计划再执行"：口径在动手之前就定死。"""
    plan = [
        "统一口径：查『月费 + 计费方式』",
        "查竞品A（按统一口径）",
        "查竞品B（按统一口径）",
        "查竞品C（按统一口径）",
        "横向对比",
    ]
    findings = {
        "竞品A": "¥99/月，按席位计费",
        "竞品B": "¥129/月，按调用量计费",
        "竞品C": "¥79/月，含 10 万 token 免费额度",
    }
    return {"findings": findings, "plan": plan}


def main() -> None:
    print("=" * 74)
    print("任务：调研三家竞品的定价策略，做横向对比")
    print("=" * 74)

    react = step1_react_style()
    print("\n【ReAct 版：走一步看一步】")
    for i, t in enumerate(react["trace"], 1):
        print(f"  第 {i} 步  {t}")
    print("\n  收集到的事实：")
    for k, v in react["findings"].items():
        print(f"    {k:<6} {v}")

    plan = step1_plan_style()
    print("\n【P&E 版：先声明路径】")
    for i, p in enumerate(plan["plan"], 1):
        print(f"  第 {i} 步  {p}")
    print("\n  收集到的事实：")
    for k, v in plan["findings"].items():
        print(f"    {k:<6} {v}")

    print("\n" + "=" * 74)
    print("问题在哪")
    print("=" * 74)
    print("  ReAct 的第 1、2 步假设了「只比价格」，第 3 步才发现口径不一致。")
    print("  于是：A 和 B 只有价格，C 只有计费方式 —— **三家没法放在一张表里比**。")
    print()
    print("  这不是模型笨。它每一步的判断，在当时的上下文里都是合理的。")
    print("  问题出在：**没有任何一步拥有全局视角。**")
    print()
    print("  👉 下一级：把「口径」从执行阶段挪到规划阶段，问题就消失了。")


if __name__ == "__main__":
    main()
