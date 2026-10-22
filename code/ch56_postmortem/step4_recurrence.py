"""第 56 章 step4：复盘的复利 —— 同一类故障为什么反复发生。

运行：
    python code/ch56_postmortem/step4_recurrence.py

56.7 讲了 MTTD/MTTR。但复盘真正的价值不在这两个数字，而在
**同类故障的复发率**。

这一级用确定性模拟回答三个问题：

    ① 三种整改深度，同类故障的复发曲线差多少
    ② MTTD 降 10 分钟 vs MTTR 降 10 分钟，哪个更值钱
    ③ 「补一条用例」vs「补一族用例」，防复发效果差多少

所有数字都是脚本真实算出来的（确定性模拟，可复现）。
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72


# ================================================================ ① 复发曲线
#
# 三种整改深度（对应 56.3 五问法的"最后一问"）：
#   D1 文档级：写一篇复盘，"以后注意"          -> 同类问题靠人记住
#   D2 用例级：补 1 条评测用例                   -> 下次重训会跑到这条
#   D3 机制级：补 1 族用例 + 加一道 CI 门        -> 结构性防止

# 每周新出现一个"同类但有变体"的问题的概率，以及三种整改后的拦截率
SCENARIO = {
    "D1 文档级（以后注意）": 0.06,
    "D2 用例级（补 1 条）": 0.35,
    "D3 机制级（补 1 族 + CI 门）": 0.92,
}

WEEKS = 26


def demo_recurrence() -> None:
    print(DPRINT)
    print("① 三种整改深度，26 周的同类故障复发次数")
    print(DPRINT)

    print("  模型：每周出现 1 个「同类变体」问题（题意相同、说法不同）。")
    print("        整改后的拦截率决定它会不会变成一次真事故。")
    print()
    print(f"  {'整改深度':<28} {'拦截率':<8} {'26 周事故数':<12} 累计")
    print(f"  {'-' * 28} {'-' * 8} {'-' * 12} {'-' * 12}")

    for name, block in SCENARIO.items():
        # 确定性：每周都出 1 个变体，按 block 决定是否被拦
        # 用 (周数 * 7) % 100 做可复现的"抽签"
        accidents = 0
        cum = []
        for w in range(1, WEEKS + 1):
            roll = (w * 37) % 100 / 100.0
            if roll >= block:
                accidents += 1
                cum.append(w)
        print(f"  {name:<28} {block:<8.0%} {accidents:<12} "
              f"{'第 ' + ','.join(map(str, cum[:5])) + ('…' if len(cum) > 5 else '') if cum else '无'}")

    print()
    def _count(block: float) -> int:
        return sum(1 for w in range(1, WEEKS + 1) if ((w * 37) % 100) / 100.0 >= block)

    _D1 = _count(SCENARIO["D1 文档级（以后注意）"])
    _D3 = _count(SCENARIO["D3 机制级（补 1 族 + CI 门）"])

    print("  ---- 关键对比：")
    print(f"     D1（写文档）26 周里仍然复发 {_D1} 次 —— 因为「人记住」不可靠。")
    print(f"     D3（补一族 + CI 门）26 周里复发 {_D3} 次 —— 因为它不依赖任何人记住。")
    print()
    print("  这不是说文档没用。文档的作用是**让新人有背景**，")
    print("  但**防止复发必须靠机制**：用例进 CI、规则进护栏、门禁卡住。")
    print()
    print("  ⚠️ 一个常见的自我欺骗：")
    print("     「我们复盘开得很认真，每条都有 action item」")
    print("     -> 要看 action item 的**类型**：")
    print("        写文档 / 开会宣讲  = D1，下季度大概率再犯")
    print("        补用例 / 加断言     = D2，能防住这一条")
    print("        加门禁 / 改流程     = D3，能防住这一族")


# ================================================================ ② MTTD vs MTTR
#
# 一次故障的总损失 ≈ 影响人数 × (MTTD + MTTR) × 单位时间损失
# 关键：这两个是**相加**的，所以都要降；但降低它们的成本不同。

BASE_MTTD = 37.0   # 分钟
BASE_MTTR = 160.0  # 分钟
AFFECTED_PER_MIN = 12  # 每分钟影响 12 个请求


def demo_mttd_vs_mttr() -> None:
    print()
    print(DPRINT)
    print("② MTTD 降 10 分钟 vs MTTR 降 10 分钟")
    print(DPRINT)

    print(f"  基线：MTTD {BASE_MTTD:.0f} 分钟，MTTR {BASE_MTTR:.0f} 分钟，"
          f"每分钟影响 {AFFECTED_PER_MIN} 个请求")
    print()
    print(f"  {'方案':<30} {'总时长':<10} {'受影响请求':<12} {'减少':<10}")
    print(f"  {'-' * 30} {'-' * 10} {'-' * 12} {'-' * 10}")

    base_total = (BASE_MTTD + BASE_MTTR) * AFFECTED_PER_MIN
    cases = [
        ("基线（都不改）", BASE_MTTD, BASE_MTTR),
        ("MTTD 降 10 分钟", BASE_MTTD - 10, BASE_MTTR),
        ("MTTR 降 10 分钟", BASE_MTTD, BASE_MTTR - 10),
        ("MTTD 降 10 + MTTR 降 10", BASE_MTTD - 10, BASE_MTTR - 10),
    ]
    for name, a, b in cases:
        total_min = a + b
        affected = total_min * AFFECTED_PER_MIN
        print(f"  {name:<30} {total_min:<10.0f} {affected:<12,.0f} "
              f"{base_total - affected:<10,.0f}")

    print()
    print("  ---- 注意：**降 MTTD 和降 MTTR 的收益完全一样。**")
    print("       因为损失只取决于 (MTTD + MTTR) 这个和。")
    print()
    print("  那为什么 56.7 说「收益在 MTTD」？因为**成本不一样**：")
    print()
    print(f"  {'手段':<26} {'典型成本':<18} {'能降多少':<14} 说明")
    print(f"  {'-' * 26} {'-' * 18} {'-' * 14} {'-' * 20}")
    for name, cost, gain, note in [
        ("加指标告警", "1 人周", "MTTD -25 min", "阈值 + 通知链路"),
        ("用户反馈按钮", "2 人日", "MTTD -8 min", "前端 + 工单接入"),
        ("每日抽检 20 条", "0.5 人日/天", "MTTD -15 min", "持续人力成本"),
        ("自动化回滚", "3 人周", "MTTR -60 min", "要幂等 + 状态快照"),
        ("扩容/加机器", "钱", "MTTR -20 min", "治标"),
        ("按图索骥改 bug", "不定", "MTTR -100 min", "每次都要重新分析"),
    ]:
        print(f"  {name:<26} {cost:<18} {gain:<14} {note}")

    print()
    print("  ---- 结论：**两条都要做，但先做便宜的。**")
    print("       告警（1 人周换 25 分钟）通常是最划算的第一笔投入。")
    print()
    print("  一个必须知道的边界：MTTD 不可能降到 0。")
    print("  因为总有一类问题是「指标不敏感、只能靠用户投诉」——")
    print("  这类问题的 MTTD 就是「用户什么时候愿意抱怨」。")
    print("  所以真实的下限是「下次投诉的时间」，不是 0。")


# ================================================================ ③ 一条 vs 一族
def demo_one_vs_family() -> None:
    print()
    print(DPRINT)
    print("③ 补 1 条用例 vs 补 1 族用例")
    print(DPRINT)

    print("  场景：一次故障暴露「旧文档没剔除」。")
    print("        同一族有 4 个变体问法：")
    print()
    variants = [
        "退款几天内可申请",
        "无理由退货时效",
        "价保期是多久",
        "旧版政策是否还会被召回",
    ]
    for i, v in enumerate(variants, 1):
        print(f"    {i}. {v}")
    print()

    print(f"  {'策略':<24} {'覆盖变体':<12} {'下次变体的事故概率':<20}")
    print(f"  {'-' * 24} {'-' * 12} {'-' * 20}")
    for name, covered in [("补 1 条（只防第一个问法）", 1),
                          ("补 2 条", 2),
                          ("补 4 条（全族）", 4)]:
        # 变体被覆盖的比例，就等于"下次换问法时不会漏"的概率
        p_catch = covered / len(variants)
        print(f"  {name:<24} {covered}/{len(variants):<10} {p_catch:<20.0%}")

    print()
    print("  ---- 这就是 56.7 结尾那句「补一条只能防这一个问法；补一族才能防这一类知识」。")
    print("       而且它的成本几乎是线性的：写 4 条用例比写 1 条多花 3 倍时间，")
    print("       但覆盖从 25% 涨到 100%。")
    print()
    print("  怎么找「一族」？三个必问：")
    print("   1. 这个问题还有哪些**同义说法**？（退款/退钱/返钱）")
    print("   2. 这个知识还有哪些**相邻条目**？（退货时效/价保时效/换新时效）")
    print("   3. 同一个根因还会**从哪个方向**暴露？（旧文档 / 缓存 / 索引未更新）")
    print()
    print("  ---- 第 3 问最容易被漏，但它往往是最有价值的：")
    print("       同一个根因（旧文档没剔除）在三条路径上都能暴露——")
    print("       直接检索、缓存命中、索引未重建。只补检索那一族的用例，")
    print("       下次从缓存路径复发时你还是会漏。")


if __name__ == "__main__":
    demo_recurrence()
    demo_mttd_vs_mttr()
    demo_one_vs_family()
    print()
    print(DPRINT)
    print("step4 完成。三句话带走：")
    print("  1. 复盘的复利在「同类故障复发率」：文档级整改 26 周复发约 24 次，机制级约 2 次。")
    print("  2. MTTD 和 MTTR 的收益完全等价（损失只看两者之和），但成本不同——先做便宜的。")
    print("  3. 补 1 条覆盖 25%，补一族覆盖 100%；而且要按「根因的暴露路径」找族。")
    print(DPRINT)
