"""第 11 章 step4：Agent 的步数成本曲线 —— 为什么「多跑几步」贵得离谱。

运行：
    python code/ch11_agent_intro/step4_step_budget.py

11.5 给了「该不该用 Agent」的判断表。但还有一个更细的问题：

    同一个 Agent，允许它多跑 2 步，成本会涨多少？

答案不是线性的。因为**每一轮都要把之前的全部历史重新发一遍**。

这一级量化三件事：
    ① 单次会话的成本随步数怎么涨（上下文累积）
    ② max_steps 设多少最划算（收益 vs 成本）
    ③ 加一个"每步做摘要"的优化，能省多少

所有数字都是脚本真实算出来的。
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72

# 单价（元/千 token），取一个常见的量级，只用于算相对值
PRICE_IN = 0.002
PRICE_OUT = 0.008

SYSTEM_PROMPT = 300     # 系统提示词字数
USER_TASK = 60          # 用户任务字数
TOOL_DESC = 240         # 全部工具描述字数
PER_STEP_OUT = 90       # 每步模型输出（含思考 + 工具调用）
PER_STEP_OBS = 180      # 每步工具返回的字数


def demo_accumulation() -> None:
    print(DPRINT)
    print("① 成本随步数怎么涨：每一轮都重发全部历史")
    print(DPRINT)

    print("  模型：第 n 轮发送的内容 = 系统提示 + 工具描述 + 用户任务")
    print("        + 前 n-1 轮的全部（模型输出 + 工具返回）")
    print()
    print(f"  {'步数':<6} {'本轮输入':<12} {'累计输入':<12} {'累计输出':<12} "
          f"{'累计成本(元)':<14} {'相对线性':<10}")
    print(f"  {'-' * 6} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 14} {'-' * 10}")

    base = SYSTEM_PROMPT + TOOL_DESC + USER_TASK
    cum_in = 0
    cum_out = 0
    for n in range(1, 11):
        # 本轮输入 = 基础 + 前 n-1 轮的历史
        this_in = base + (n - 1) * (PER_STEP_OUT + PER_STEP_OBS)
        cum_in += this_in
        cum_out += PER_STEP_OUT
        cost = cum_in / 1000 * PRICE_IN + cum_out / 1000 * PRICE_OUT
        # 线性基线：假设每轮只发增量
        linear = (base * n) / 1000 * PRICE_IN + cum_out / 1000 * PRICE_OUT
        print(f"  {n:<6} {this_in:<12,} {cum_in:<12,} {cum_out:<12,} "
              f"{cost:<14.6f} {cost / linear:<10.2f}x")

    print()
    print("  ---- 关键：第 10 步**单轮输入**是第 1 步的 "
          f"{(base + 9 * (PER_STEP_OUT + PER_STEP_OBS)) / base:.1f} 倍。")
    print(f"       而**累计成本**从 {0.001920:.6f} 涨到 {0.043500:.6f}，"
          f"是 1 步的 {0.043500 / 0.001920:.1f} 倍。")
    print("       ---- 10 步的累计输入（18,150）是「线性」假设（6,000）的 3.0 倍：")
    print("            因为每一步都要把之前所有历史重发一遍。")
    print()
    print("  这就是「多跑 2 步」贵得离谱的原因：")
    print("  不是多跑 2 步，而是**后面每一步都变贵了 2 步的量**。")


def demo_max_steps() -> None:
    print()
    print(DPRINT)
    print("② max_steps 设多少最划算")
    print(DPRINT)

    # 假设：任务真实完成所需步数分布（大部分 3~5 步，少数 8+）
    # 每多允许 1 步，能"救回"一部分本来会失败的任务，但所有任务都可能多跑
    print("  假设：任务真实完成所需步数分布")
    dist = {3: 0.42, 4: 0.28, 5: 0.15, 6: 0.08, 7: 0.04, 8: 0.03}
    for k, v in dist.items():
        print(f"    {k} 步: {v:.0%}")
    print()
    print("  成本模型：允许 N 步时，失败任务会一直跑到 N 步才放弃。")

    def avg_cost(n_max: int) -> float:
        total = 0.0
        for need, p in dist.items():
            steps = min(need, n_max)
            cum_in = sum(
                SYSTEM_PROMPT + TOOL_DESC + USER_TASK + (i - 1) * (PER_STEP_OUT + PER_STEP_OBS)
                for i in range(1, steps + 1)
            )
            cum_out = steps * PER_STEP_OUT
            total += p * (cum_in / 1000 * PRICE_IN + cum_out / 1000 * PRICE_OUT)
        return total

    def success(n_max: int) -> float:
        return sum(p for need, p in dist.items() if need <= n_max)

    print()
    print(f"  {'max_steps':<11} {'成功率':<10} {'平均成本(元)':<16} {'每次成功成本(元)':<18} 判断")
    print(f"  {'-' * 11} {'-' * 10} {'-' * 16} {'-' * 18} {'-' * 20}")

    best = None
    for n in range(2, 10):
        s = success(n)
        c = avg_cost(n)
        per_success = c / s if s else float("inf")
        if best is None or per_success < best[1]:
            best = (n, per_success, s)
    for n in range(2, 10):
        s = success(n)
        c = avg_cost(n)
        per_success = c / s if s else float("inf")
        judge = "← 最优" if n == best[0] else ""
        print(f"  {n:<11} {s:<10.2%} {c:<16.6f} {per_success:<18.6f} {judge}")

    print()
    print(f"  ---- 最优在 max_steps={best[0]}：成功率 {best[2]:.0%}，"
          f"每次成功成本 {best[1]:.6f} 元。")
    print("  ---- 这个例子边际收益一直没转负，因为分布里最长的任务正好 8 步。")
    print("       真实项目里再往上加就会出现「白烧步数」：")
    print("       失败的长尾任务会一直跑到上限才放弃，把平均成本拉高。")
    print()
    print("  看 max_steps=4 vs 8 的取舍（这是真正要判断的地方）：")
    for n in (4, 6, 8):
        s = success(n)
        per = avg_cost(n) / s
        print(f"     max={n}: 成功率 {s:.0%}，每次成功成本 {per:.6f} 元")
    print("  ---- 从 4 到 8，每次成功成本只降 12%，但成功率从 70% 涨到 100%。")
    print("       **成功率的价值通常远大于这点成本差** —— 一次失败的用户流失，")
    print("       比多花的 0.002 元贵几个数量级。")
    print()
    print("  一个实用的做法：**max_steps = P95(真实完成步数) + 2**。")
    print("  用它自己的日志算 P95，不要抄别人的 10 或 20。")


def demo_summary_trick() -> None:
    print()
    print(DPRINT)
    print("③ 每步做摘要：省多少，丢多少")
    print(DPRINT)

    print("  做法：每 3 步把前面的历史压成一段摘要（假设 120 字），替代原文。")
    print()
    print(f"  {'步数':<6} {'不摘要累计输入':<16} {'摘要后累计输入':<18} {'省':<8}")
    print(f"  {'-' * 6} {'-' * 16} {'-' * 18} {'-' * 8}")

    base = SYSTEM_PROMPT + TOOL_DESC + USER_TASK
    SUMMARY = 120

    cum_a = 0
    cum_b = 0
    for n in range(1, 16):
        # 不摘要
        this_a = base + (n - 1) * (PER_STEP_OUT + PER_STEP_OBS)
        cum_a += this_a
        # 摘要：每 3 步压一次，历史只保留最近不足 3 步的原文 + 摘要
        n_summaries = (n - 1) // 3
        recent = (n - 1) % 3
        this_b = base + n_summaries * SUMMARY + recent * (PER_STEP_OUT + PER_STEP_OBS)
        cum_b += this_b
        if n in (3, 5, 6, 9, 12, 15):
            print(f"  {n:<6} {cum_a:<16,} {cum_b:<18,} {1 - cum_b / cum_a:<8.0%}")

    print()
    print("  ---- 15 步时省 55%，且省的比例随步数单调上升。")
    print()
    print("  但摘要的代价是三件事，必须一起算：")
    print("   1. **摘要本身要花钱**（一次模型调用，本模型没算进去）")
    print("   2. **摘要会丢证据**（第 36 章实测：丢的几乎全是数字/编号）")
    print("   3. **摘要会让调试变难**（出了问题看不到原始历史）")
    print()
    print("  所以：**短任务别摘要，长任务用结构化黑板而不是自由文本摘要。**")
    print("  （第 23.5.1 节的 pinned + 滚动 + errors 不裁，就是结构化版本。）")


if __name__ == "__main__":
    demo_accumulation()
    demo_max_steps()
    demo_summary_trick()
    print()
    print(DPRINT)
    print("step4 完成。三句话带走：")
    print("  1. Agent 成本随步数是**二次增长**：第 n 轮要重发前 n-1 轮的全部历史。")
    print("  2. max_steps 有个平衡点：太小成功率掉，太大失败任务白烧。")
    print("     本例从 4 到 8 只多花 12% 成本，却把成功率从 70% 拉到 100%。")
    print("     用你自己的 P95 + 2，别抄别人的 10 或 20。")
    print("  3. 每步摘要在长任务上能省 55%，但会丢证据、加调试难度——")
    print("     长任务用结构化黑板，不用自由文本摘要。")
    print(DPRINT)
