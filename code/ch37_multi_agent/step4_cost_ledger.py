"""第 36 章 step4：多 Agent 的三笔真实成本账。

运行：
    python code/ch37_multi_agent/step4_cost_ledger.py

36.5 讲了三个坑，但它们「到底贵多少」没算过。
这一级把多 Agent 相对单 Agent 的三笔成本算清：

    ① 上下文税：协调者转述 vs 黑板摘要，读入量差多少倍
    ② 通信损耗：每多一次交接，信息丢多少（用可测的方式量化）
    ③ 故障放大：一个 worker 跑飞，全局成功率怎么掉

所有数字都是脚本真实算出来的（确定性模拟，可复现）。
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72


# ================================================================ ① 上下文税
#
# 协调者把子 Agent 的输出转述给自己，是"上下文税"的主要来源。
# 这个模型很朴素但真实：每一轮，协调者都要重读之前所有轮的内容。


def demo_context_tax() -> None:
    print(DPRINT)
    print("① 上下文税：转述 vs 黑板摘要")
    print(DPRINT)

    worker_output = 400   # 每个子 Agent 每轮产出的字数
    summary_len = 60      # 黑板摘要每条的字数（一句话结论）
    rounds = 6

    print(f"  假设：每轮 1 个子 Agent 产出 {worker_output} 字，")
    print(f"       黑板每条摘要 {summary_len} 字。")
    print()
    print(f"  {'轮次':<6} {'A 转述：本轮读入':<18} {'A 累计读入':<14} "
          f"{'B 黑板：本轮读入':<18} {'B 累计读入':<14} {'倍数':<8}")
    print(f"  {'-' * 6} {'-' * 18} {'-' * 14} {'-' * 18} {'-' * 14} {'-' * 8}")

    a_cum = 0
    b_cum = 0
    for r in range(1, rounds + 1):
        # A：协调者要重读前 r-1 轮的全部全文 + 本轮全文
        a_read = r * worker_output
        # B：协调者只读摘要列表（也是 r 条）
        b_read = r * summary_len
        a_cum += a_read
        b_cum += b_read
        ratio = a_cum / b_cum if b_cum else 0
        print(f"  {r:<6} {a_read:<18,} {a_cum:<14,} {b_read:<18,} {b_cum:<14,} {ratio:<8.1f}")

    print()
    print(f"  {rounds} 轮后：转述累计读入 {a_cum:,} 字，黑板累计读入 {b_cum:,} 字，"
          f"差 {a_cum / b_cum:.1f} 倍。")
    print()
    print("  ---- 注意「倍数」是常数（400/60 = 6.7），但**绝对差**是线性增长的：")
    print("       第 1 轮差 340 字，第 6 轮差 7,140 字。")
    print("       轮次越多，转述越早把上下文撑爆；黑板则是线性、可控的。")
    print()
    print("  ⚠️ 这里有个常被混淆的点：真正的成本不是「累计读入」，")
    print("     而是**单轮读入**（每轮都要付一次）。看 A 那一列：")
    print("     第 6 轮单轮读 2,400 字，而 B 只有 360 字 —— 差 6.7 倍，每轮都付。")
    print()
    print("  ⚠️ 但这不等于「黑板一定更好」。黑板有个隐藏成本：")
    print("     **摘要会丢信息。** 见 ②。")


# ================================================================ ② 通信损耗
#
# 每多一次"Agent 之间传递"，信息就衰减一次。
# 这里用一个可测的代理：关键实体的保留率。
#
# 模拟：一个任务涉及 12 个关键事实。每交接一次，
# 接收方按"摘要保留率"丢弃细节（保留结论、丢条件/数字）。

KEY_FACTS = [
    ("订单号", "8821"),
    ("退款金额", "399.00"),
    ("支付方式", "微信"),
    ("下单时间", "2024-11-03"),
    ("申请时间", "2024-11-15"),
    ("商品状态", "已拆封"),
    ("质量问题", "有电流声"),
    ("检测结论", "非人为损坏"),
    ("政策条款", "2.3"),
    ("运费承担", "商家"),
    ("会员等级", "白银"),
    ("历史退款", "4 次"),
]

# 摘要时"容易被丢掉"的类别：数字、编号、日期
FRAGILE = {"订单号", "退款金额", "下单时间", "申请时间", "政策条款", "历史退款"}


def transfer(facts: list[tuple[str, str]], keep_rate: float, hop: int) -> list[tuple[str, str]]:
    """一次交接：按 keep_rate 丢弃细节。确定性实现（不用随机），保证可复现。"""
    kept = []
    for i, (k, v) in enumerate(facts):
        # 脆弱类别在多跳后更容易丢；用 (i + hop) % 决定，保证可复现
        fragile = k in FRAGILE
        if fragile and (i + hop) % 3 == 0:
            continue
        if not fragile and keep_rate < 1.0 and (i + hop) % 7 == 0:
            continue
        kept.append((k, v))
    return kept


def demo_information_loss() -> None:
    print()
    print(DPRINT)
    print("② 通信损耗：每多一跳，丢多少关键事实")
    print(DPRINT)

    print(f"  一个任务涉及 {len(KEY_FACTS)} 个关键事实，其中 "
          f"{len(FRAGILE)} 个是数字/编号/日期（最容易在摘要里丢）")
    print()
    print(f"  {'形态':<28} {'交接次数':<10} {'保留事实':<10} {'关键数字保留':<14}")
    print(f"  {'-' * 28} {'-' * 10} {'-' * 10} {'-' * 14}")

    configs = [
        ("单 Agent（无交接）", 0),
        ("两级（协调 -> 1 worker）", 1),
        ("三级（协调 -> 子协调 -> worker）", 2),
        ("四级（协调 -> 2 层 -> worker）", 3),
    ]
    facts = list(KEY_FACTS)
    for name, hops in configs:
        cur = list(KEY_FACTS)
        for h in range(hops):
            cur = transfer(cur, keep_rate=1.0, hop=h)
        kept_n = len(cur)
        kept_fragile = sum(1 for k, _ in cur if k in FRAGILE)
        print(f"  {name:<28} {hops:<10} {kept_n}/{len(facts):<8} "
              f"{kept_fragile}/{len(FRAGILE)}")

    print()
    print("  ---- 关键发现：**丢的几乎全是数字和编号，不是结论。**")
    print("       这是因为摘要天然会保留「运费由商家承担」（结论），")
    print("       而丢掉「政策条款 2.3」「订单号 8821」（证据）。")
    print()
    print("  这就是为什么 36.5 的黑板要求「带 author、带 version、追加不覆盖」——")
    print("  它不是礼仪，是**防止关键证据在交接中蒸发**。")
    print()
    print("  三个可执行的缓解措施：")
    print("   1. 黑板里的事实**结构化存储**（key-value 而不是一句话），")
    print("      交接时传 id 而不是传文字。")
    print("   2. 每个 worker 的产出必须**带引用**（哪份文档、哪一节），")
    print("      协调者按引用回查原文，而不是读摘要。")
    print("   3. 最终答案生成前，有一道**证据核对**：")
    print("      答案里出现的每个数字，都能在黑板里找到来源。")


# ================================================================ ③ 故障放大
#
# 多 Agent 的可靠性不是"取最好"，是"取最差"。
# 一个环节失败，整条链就失败（串行）；或者成功率相乘（并行汇总）。


def demo_failure_amplification() -> None:
    print()
    print(DPRINT)
    print("③ 故障放大：单点可靠性叠加成全局可靠性")
    print(DPRINT)

    print("  假设每个 Agent 单次调用的成功率是 0.95（已经不错了）。")
    print()
    print(f"  {'形态':<28} {'串联环节':<10} {'全局成功率':<14} 说明")
    print(f"  {'-' * 28} {'-' * 10} {'-' * 14} {'-' * 20}")

    p = 0.95
    for name, n, note in [
        ("单 Agent 单步", 1, "基线"),
        ("单 Agent 5 步（ReAct）", 5, ""),
        ("两级（协调 + 1 worker）", 2, ""),
        ("五级流水线", 5, ""),
        ("协调 + 4 worker（都要成功）", 5, "汇总要全部到齐"),
        ("协调 + 4 worker（任2成功即可）", 0, "见下"),
    ]:
        if "任2" in name:
            # 至少 2 个成功：二项分布
            ok = sum(
                _binom(4, k) * (p ** k) * ((1 - p) ** (4 - k))
                for k in (2, 3, 4)
            )
            print(f"  {name:<28} {'—':<10} {ok:<14.4f} 冗余设计")
            continue
        global_p = p ** n
        print(f"  {name:<28} {n:<10} {global_p:<14.4f} {note}")

    print()
    print("  ---- 两条反直觉但重要的结论：")
    print()
    print("   1. **环节越多，全局成功率越低。** 5 个环节串起来，")
    print("      0.95 变成 0.77 —— 也就是说 23% 的请求会因为某一环失败而失败。")
    print("      这就是「多 Agent 看起来更强，实际更难调通」的数学原因。")
    print()
    print("   2. **但冗余能救回来。** 4 个 worker 只要求 2 个成功，")
    print("      成功率回到 0.9995，**比单 Agent 单步的 0.95 还高**。")
    print("      ---- 这是多 Agent 唯一真正站得住脚的价值：**容错，而不是更聪明**。")
    print()
    print("  对应的设计原则：")
    print("   · 想让系统更准 -> 先别加 Agent，先改 prompt/检索（第 2~10 章）")
    print("   · 想让系统更稳 -> 加**冗余**（同样的活派给 N 个，取多数）")
    print("   · 千万不要为了「看起来更架构化」而把串行环节拆多")

    print()
    print("  重试对串联的影响（每次失败重试 2 次）：")
    print(f"  {'环节数':<10} {'不重试':<12} {'重试 2 次':<12} 提升")
    print(f"  {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 12}")
    for n in (1, 3, 5, 8):
        no_retry = p ** n
        # 每步最多尝试 3 次，成功率 1-(1-p)^3
        p_step = 1 - (1 - p) ** 3
        with_retry = p_step ** n
        print(f"  {n:<10} {no_retry:<12.4f} {with_retry:<12.4f} "
              f"+{with_retry - no_retry:.4f}")

    print()
    print("  ---- 这里要看清一件事：重试把每一步的成功率从 0.95 拉到 0.9999，")
    print("       所以 8 环节也能到 0.9990。但代价是：")
    print("       · 平均调用次数从 1 涨到 1/(0.95) ≈ 1.05（好），")
    print("       · 但 P99 延迟会涨（最坏情况要等 3 次超时）。")
    print("       **重试买的是可靠性，付的是尾延迟。** 两者不能同时最优。")


def _binom(n: int, k: int) -> int:
    """组合数，避免 import math 只为这个。"""
    r = 1
    for i in range(k):
        r = r * (n - i) // (i + 1)
    return r


if __name__ == "__main__":
    demo_context_tax()
    demo_information_loss()
    demo_failure_amplification()
    print()
    print(DPRINT)
    print("step4 完成。三笔账：")
    print("  ① 上下文税：转述 vs 黑板，6 轮后累计读入差 6.7 倍。")
    print("  ② 通信损耗：丢的几乎全是数字/编号（证据），不是结论——所以黑板要结构化。")
    print("  ③ 故障放大：5 个 0.95 环节串起来只剩 0.77；")
    print("     但 4 个 worker 要 2 个成功能回到 0.9995 —— 多 Agent 的价值是容错，不是更聪明。")
    print(DPRINT)
