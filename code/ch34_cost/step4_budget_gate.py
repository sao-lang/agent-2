"""第 35 章 step4：三级预算闸门 —— 怎么让一次事故不要变成一张账单（离线）。

运行：
    python code/ch34_cost/step4_budget_gate.py

上一级的痛点：优化是"平均值"的事，但成本事故是"长尾"的事。
             一个月平均 ¥0.03/次，挡不住某一次请求烧了 200 次调用。
这一级做什么：把闸门放在三个层级上，并把"拒绝"本身变成一个可解释的动作。

三级：
  请求级  一次请求最多花多少   → 防"跑飞"
  会话级  一个用户一次会话最多 → 防"反复重试"
  租户级  一个客户一天最多     → 防"把系统吃满"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cost import BudgetManager, BudgetScope  # noqa: E402


def try_spend(bm: BudgetManager, cost: float, label: str) -> bool:
    ok, why = bm.check(cost)
    if ok:
        bm.spend(cost)
        print(f"  {label:<28}¥{cost:.4f}  → 允许    余量：请求 ¥{bm.request.remaining:.4f}")
    else:
        print(f"  {label:<28}¥{cost:.4f}  → 拒绝    {why}")
    return ok


def main() -> None:
    print("=" * 76)
    print("① 一个正常的请求（5 次调用）")
    print("=" * 76)
    bm = BudgetManager(
        request=BudgetScope("请求", limit=0.05),
        session=BudgetScope("会话", limit=0.80),
        tenant=BudgetScope("租户", limit=20.0),
    )
    for i, c in enumerate([0.002, 0.004, 0.012, 0.016, 0.003], 1):
        try_spend(bm, c, f"第 {i} 次调用")
    print(f"\n  本请求合计 ¥{bm.request.used:.4f} / 上限 ¥{bm.request.limit:.2f}")

    print("\n" + "=" * 76)
    print("② 一个失控的请求（Agent 陷入循环）")
    print("=" * 76)
    bm2 = BudgetManager(
        request=BudgetScope("请求", limit=0.05),
        session=BudgetScope("会话", limit=0.80),
        tenant=BudgetScope("租户", limit=20.0),
    )
    n = 0
    while True:
        n += 1
        ok, why = bm2.check(0.012)
        if not ok:
            print(f"  第 {n} 次调用被拦：{why}")
            n -= 1                      # 被拦的这次没有花钱
            break
        bm2.spend(0.012)

    protected = n * 0.012
    unbounded = 200 * 0.012
    print()
    print(f"  没有闸门：按循环 200 次算 = ¥{unbounded:.2f}")
    print(f"  有闸门  ：在第 {n} 次停下 = ¥{protected:.2f}")
    print(f"  → 单次事故省下 ¥{unbounded - protected:.2f}（{(1 - protected / unbounded):.0%}）")

    print("\n" + "=" * 76)
    print("③ 三个层级分别挡住什么")
    print("=" * 76)
    print(f"  {'层级':<8}{'典型上限':<14}{'挡住什么'}")
    print("  " + "-" * 68)
    print(f"  {'请求':<8}{'单次成本的 2~3 倍':<14}{'一次请求跑飞（循环、重试风暴）'}")
    print(f"  {'会话':<8}{'单次成本的 20~30 倍':<14}{'用户反复重试 / 恶意刷'}")
    print(f"  {'租户':<8}{'按合同/套餐':<14}{'某个客户把整个系统吃满'}")

    print("\n" + "=" * 76)
    print("★ 预算上限必须回答的三个问题")
    print("=" * 76)
    print("  1. 超了之后怎么办？")
    print("     · 直接报错（用户体验差）")
    print("     · 降级到小模型继续（推荐）")
    print("     · 转人工 / 排队到明天")
    print("     → 本章代码只做'拒绝'，生产里应该选择'降级'。")
    print()
    print("  2. 余量怎么让人知道？")
    print("     前端要显示'本次对话剩余额度'，否则用户不知道为什么被拦。")
    print()
    print("  3. 谁来调整上限？")
    print("     上限写在代码里 → 每次调整都要发版；")
    print("     上限放配置中心 → 快，但**改错了就是全站事故**。")
    print("     → 推荐：配置中心 + 变更审批 + 一条'上限被改动'的告警。")

    print("\n" + "=" * 76)
    print("④ 一个真实的失控现场")
    print("=" * 76)
    print("  第 58 章的四种失控里，最贵的是『重试风暴』：")
    print("    模型返回了不合法的 JSON → 重试 → 还不合法 → 再重试 …")
    print("  每次重试都带完整上下文，成本是线性叠加的。")
    print()
    print(f"  本例中，闸门在第 {n} 次调用时停下 —— 没有闸门的话，")
    normal = bm.request.used
    print(f"  一次请求就可能花掉 ¥{unbounded:.2f}，是正常请求（¥{normal:.3f}）的 {unbounded / normal:.0f} 倍。")

    print("\n" + "=" * 76)
    print("结论")
    print("=" * 76)
    print("  预算上限不省钱 —— 它**防事故**。")
    print("  而事故的特征是：不常发生，一旦发生就上头条。")
    print("  所以它是四个杠杆里，唯一一个『今天就能加、且不需要评测』的。")


if __name__ == "__main__":
    main()
