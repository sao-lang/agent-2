"""第 35 章 step5：把数字翻译成业务语言（离线）。

运行：
    python code/ch35_cost/step5_business_report.py

上一级的痛点：有了归因、有了优化，但**你还得说服业务方**。
这一级做什么：同一个事实，三种说法。前两种会被打回来，第三种能过。

事实：本月成本 ¥8,420，上月 ¥2,780，涨了 3 倍。
"""
from __future__ import annotations

print("说明：本文件是'说法'的对照，不涉及代码逻辑，直接打印。")
print()

MONTH_COST = 8420.0
LAST_MONTH = 2780.0
LAST_USERS = 720          # 用户涨 2.5 倍（720 -> 1800），而成本涨 3.03 倍
USERS = 1800          # 本月
REQUESTS = 62_000
TOKENS_IN = 41_000_000
TOKENS_OUT = 6_800_000

growth = MONTH_COST / LAST_MONTH - 1
per_user = MONTH_COST / USERS
per_request = MONTH_COST / REQUESTS


def main() -> None:
    print("=" * 78)
    print("事实（本月 vs 上月）")
    print("=" * 78)
    print(f"  成本      ¥{LAST_MONTH:,.0f} → ¥{MONTH_COST:,.0f}   （{growth:+.0%}）")
    print(f"  用户      {LAST_USERS:,} → {USERS:,}   （{USERS / LAST_USERS - 1:+.0%}）")
    print(f"  活跃用户  {USERS:,} 人")
    print(f"  请求量    {REQUESTS:,} 次")
    print(f"  每用户    ¥{per_user:.2f}/月")
    print(f"  每请求    ¥{per_request:.4f}")

    print("\n" + "=" * 78)
    print("说法 A（会被打回来）")
    print("=" * 78)
    print("  『本月成本涨了 200%，主要是因为 token 用量增加了。』")
    print()
    print("  为什么会被打回来：")
    print("    · 业务方听不懂「token 用量」是什么")
    print("    · 「涨了 200%」听起来像失控，但没说是好是坏")
    print("    · 没有一个可以行动的结论")

    print("\n" + "=" * 78)
    print("说法 B（看着专业，仍然会被打回来）")
    print("=" * 78)
    print(f"  『本月 token 输入 {TOKENS_IN:,}、输出 {TOKENS_OUT:,}，")
    print("    输入输出比 6:1，建议优化 prompt 长度。』")
    print()
    print("  为什么还是不行：")
    print("    · 它是「技术指标」，不是「业务结论」")
    print("    · 输入输出比 6:1 在 RAG 场景里**完全正常**（材料本来就长）")
    print("    · 「优化 prompt 长度」是一个方向，不是一个可验收的动作")

    print("\n" + "=" * 78)
    print("说法 C（能过）")
    print("=" * 78)
    print(f"  『本月成本 ¥{MONTH_COST:,.0f}，比上月多 ¥{MONTH_COST - LAST_MONTH:,.0f}。")
    print("    拆开看是三件事：")
    print(f"      1. 用户涨了 {USERS / LAST_USERS:.1f} 倍，成本涨了 {MONTH_COST / LAST_MONTH:.2f} 倍，")
    print(f"         单用户成本从 ¥{LAST_MONTH / LAST_USERS:.2f} 涨到 ¥{per_user:.2f}"
          f"（+{per_user / (LAST_MONTH / LAST_USERS) - 1:.0%}）—— 单位经济性**变差了**，")
    print("         这是本次要查的第一件事。")
    print("      2. 但 62,000 次请求里有 40% 是重复问题，缓存没开。")
    print(f"         开了之后，这部分约值 ¥{MONTH_COST * 0.4 * 0.9:,.0f}/月。")
    print("      3. 有 3 次请求因为重试风暴各花了 ¥2+，闸门没设。")
    print("         加上三级预算后，这类尖峰会消失。")
    print()
    print("    结论：涨**主要**来自用量，但单位成本同时涨了 21%，不能全甩给增长。")
    print("    两个动作（开缓存 + 设闸门）预计下月成本回落到 ¥5,000 以内，")
    print("    且不影响任何效果指标。』")

    print("\n" + "=" * 78)
    print("★ 三种说法的差别在哪")
    print("=" * 78)
    print(f"  {'':<8}{'说的是什么':<22}{'业务方能不能行动'}")
    print("  " + "-" * 62)
    print(f"  {'A':<8}{'总量变化':<22}{'不能 —— 只知道贵了'}")
    print(f"  {'B':<8}{'技术指标':<22}{'不能 —— 不知道改哪、改了有什么用'}")
    print(f"  {'C':<8}{'变化归因 + 可验收动作':<22}{'**能** —— 两个动作、两个预期数字'}")

    print("\n" + "=" * 78)
    print("★★ 一个必须说清楚的判断：涨 200% 是好是坏")
    print("=" * 78)
    print("  如果用户涨 250%、成本涨 200% —— **单位成本下降了**，这是好事（增长健康）。")
    print("  如果用户涨 150%、成本涨 303% —— **单位成本涨了 21%**，这是要查的问题。")
    print(f"  本次就是后一种：单用户 ¥{LAST_MONTH / LAST_USERS:.2f} → ¥{per_user:.2f}。")
    print()
    print("  很多成本汇报的失败，不是因为数字不准，")
    print("  而是因为**没有把「总量」换算成「单位」**。")
    print()
    print("  换算之后，一句话就能定性：")
    print(f"    单用户月成本 ¥{per_user:.2f}，单请求 ¥{per_request:.4f}。")

    print("\n" + "=" * 78)
    print("报表的三条铁律")
    print("=" * 78)
    print("  1. 永远给「单位成本」，不只是总量")
    print("     单请求 / 单用户 / 单会话 —— 至少一个。")
    print()
    print("  2. 永远给「和上次比」，并说明变化来自量还是效率")
    print("     量涨 = 好消息；效率降 = 要修的事。")
    print()
    print("  3. 永远给「一个可验收的动作 + 预期数字」")
    print("     不是「建议优化」，而是「开缓存，预计省 ¥3,000/月」。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  成本工程的前三步是技术活，第四步（报表）是**翻译活**。")
    print("  前 90% 的团队做到第三步就停了，于是每次成本上涨都像一场事故。")
    print(f"\n  本月的定性结论：单用户 ¥{per_user:.2f}/月，单请求 ¥{per_request:.4f}。")


if __name__ == "__main__":
    main()
