"""第 33 章 step1：每步都弹窗会发生什么（离线，纯计算）。

运行：
    python code/ch33_hitl/step1_approval_fatigue.py

上一级的痛点：无（这是起点）。
这一级做什么：算一笔账 —— 如果**每个写操作**都要人确认，
             一个人一天要处理多少个审批框？他会不会认真看？

这一级不给答案，只给数字。数字会告诉你为什么"分级"不是可选项。
"""
from __future__ import annotations

from dataclasses import dataclass

# 一个真实客服场景的一天（单个坐席）
# (动作类型, 每天次数, 是否可逆)
DAILY_ACTIONS = [
    ("查订单", 240, True),
    ("查物流", 180, True),
    ("加备注", 90, True),          # 可回滚
    ("改地址", 35, False),         # 收货后不可撤回
    ("发邮件", 28, False),
    ("退款", 22, False),           # 涉及钱
    ("取消订单", 9, False),
]

# 人工处理一个审批框的真实耗时（秒）：
# 读影响面 8s + 看参数 5s + 判断 12s + 点击 3s
SECONDS_PER_APPROVAL = 28
WORKDAY_SECONDS = 8 * 3600
# 经验值：单次审批会认真看的上限（再往上就进入"条件反射点通过"）
FATIGUE_THRESHOLD = 40
# 单日能保持注意力的审批总量上限（超过它，整体漏判率按 BLIND 算）
DAILY_ATTENTION_CAP = 120
# 无脑点击时的漏判率（研究里通常 25%~50%，取中位）
BLIND_APPROVE_MISS_RATE = 0.30


@dataclass
class Strategy:
    name: str
    needs_approval: bool


def main() -> None:
    total = sum(n for _, n, _ in DAILY_ACTIONS)
    irreversible = [(a, n) for a, n, ok in DAILY_ACTIONS if not ok]

    print("=" * 78)
    print("一个客服坐席的一天")
    print("=" * 78)
    print(f"{'动作':<12}{'次数':>8}{'可逆':>8}")
    print("-" * 30)
    for name, n, ok in DAILY_ACTIONS:
        print(f"{name:<12}{n:>8}{'是' if ok else '否':>8}")
    print(f"\n  合计 {total} 次动作，其中不可逆 {sum(n for _, n in irreversible)} 次。")

    strategies = [
        Strategy("策略 A：每个动作都确认", True),
        Strategy("策略 B：只有不可逆才确认", False),
    ]

    print("\n" + "=" * 78)
    print("两种策略下，人要处理多少审批框")
    print("=" * 78)
    print(f"{'策略':<24}{'审批数':>10}{'耗时(分钟)':>14}{'占工作日':>12}   是否超出疲劳阈值")
    print("-" * 78)
    for st in strategies:
        count = total if st.needs_approval else sum(n for _, n in irreversible)
        minutes = count * SECONDS_PER_APPROVAL / 60
        share = count * SECONDS_PER_APPROVAL / WORKDAY_SECONDS
        over = "超出" if count > DAILY_ATTENTION_CAP else "未超"
        print(f"{st.name:<24}{count:>10}{minutes:>14.0f}{share:>12.0%}   {over}")

    print("\n" + "=" * 78)
    print("★ 疲劳的代价不是『慢』，是『错』")
    print("=" * 78)
    count_a = total
    expected_miss = round(count_a * BLIND_APPROVE_MISS_RATE)
    count_b = sum(n for _, n in irreversible)
    print(f"  策略 A：{count_a} 个审批框/天。远超单日注意力上限 {DAILY_ATTENTION_CAP}，"
          f"人从某个点开始就是『条件反射点通过』。")
    print(f"          按 {BLIND_APPROVE_MISS_RATE:.0%} 的漏判率，一天约有 {expected_miss} 次异常没被看见。")
    print()
    print(f"  策略 B：{count_b} 个审批框/天 —— 仍高于单次认真看的 {FATIGUE_THRESHOLD}，"
          f"但没到注意力上限，可以靠『批量审批 + 摘要』补救。")
    print()
    print("  这就是反直觉的地方：")
    print("    **审批框越多，安全性越低。**")
    print("    因为人会疲劳，而疲劳让你失去了『最后一道人肉防线』。")

    print("\n" + "=" * 78)
    print("该确认哪些？用两个判据筛")
    print("=" * 78)
    print(f"  {'判据':<22}{'含义':<34}{'例子'}")
    print("  " + "-" * 76)
    print(f"  {'可逆吗':<22}{'能不能撤回来':<34}{'改备注 vs 退款'}")
    print(f"  {'影响谁':<22}{'只影响自己 vs 影响客户资金/权益':<34}{'查询 vs 取消订单'}")
    print()
    print("  两个判据都过 → 才需要人确认。只有一条中 → 可以 NOTIFY（执行后通知）。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  HITL 的第一个设计决策不是『怎么弹窗』，而是**『哪些不该弹』**。")
    print("  下一级把这条变成代码：四档分级 + 显式映射表。")
    print("\n  （本文件的耗时/漏判率是行业经验值，你的场景请换成自己的实测数据。）")


if __name__ == "__main__":
    main()
