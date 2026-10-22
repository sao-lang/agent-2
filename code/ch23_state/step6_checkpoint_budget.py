"""第 23 章 step6：检查点大小与裁剪 —— 用真实字节数决定「留几条」。

运行：
    python code/ch23_state/step6_checkpoint_budget.py

第 23.5 节说「facts 存摘要 + 引用」，但没给数字。
这一级把「该留几条」变成可算的东西：

    ① 一条 fact 到底占多少字节（含 JSON 开销）
    ② 不同保留策略下，检查点随时间怎么长
    ③ 全量历史 vs 滚动窗口 vs 摘要+引用：三者的字节数与"还能答对多少"
    ④ 一个常被忽略的成本：反序列化时间

所有数字都是脚本真实算出来的。
"""
from __future__ import annotations

import json
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72


# ================================================================ 一条 fact 有多重
#
# 真实的长任务里，一步产出可能是一段几百字的分析。
# 这里用一段"典型长度"的中文来算，不是编的短句。

SAMPLE_FACTS = [
    "已确认用户是 2023 年 3 月注册的企业版客户，合同编号 C-2023-0317，当前服务等级为白银。",
    "订单 8821 的退款申请已经提交，财务系统显示状态为「待审核」，预计 T+3 个工作日完成。",
    "知识库检索命中 3 篇政策文档，其中《退换货政策 v4》第 2.3 节明确说明质量问题由商家承担运费。",
    "客服系统记录显示该用户过去 6 个月有 4 次退款申请，均在 7 个工作日内完成，无投诉记录。",
    "风控模块给出的评分是 12（满分 100，越低越安全），没有触发任何人工复核规则。",
]


def demo_fact_weight() -> None:
    print(DPRINT)
    print("① 一条 fact 到底占多少字节")
    print(DPRINT)

    print(f"  {'#':<4} {'字符数':<8} {'UTF-8 字节':<12} {'JSON 内字节':<12}")
    print(f"  {'-' * 4} {'-' * 8} {'-' * 12} {'-' * 12}")
    total_json = 0
    for i, f in enumerate(SAMPLE_FACTS, 1):
        raw = len(f.encode("utf-8"))
        # JSON 序列化后会多出引号、可能的转义，以及逗号
        j = len(json.dumps(f, ensure_ascii=False).encode("utf-8")) + 1
        total_json += j
        print(f"  {i:<4} {len(f):<8} {raw:<12} {j:<12}")

    avg = total_json / len(SAMPLE_FACTS)
    print()
    print(f"  平均一条 fact（含 JSON 开销）= {avg:.1f} 字节")
    print(f"  平均一条 fact（按字符数）=   {sum(len(f) for f in SAMPLE_FACTS) / len(SAMPLE_FACTS):.1f} 字符")
    ratio = avg / (sum(len(f) for f in SAMPLE_FACTS) / len(SAMPLE_FACTS))
    print("  ---- 关键：**中文一个字符最多 3 字节**（ASCII 只占 1 字节，所以真实倍数更低）。")
    print(f"       本样本里平均一条 {sum(len(f) for f in SAMPLE_FACTS) / len(SAMPLE_FACTS):.0f} 字符、{avg:.0f} 字节，"
          f"是字符数的 {ratio:.1f} 倍。")
    print("       用 len(str) 估容量会**低估**，低估多少取决于中文/ASCII 比例。")
    print()
    print("  一个 '引用' 长什么样（替代原文）：")
    ref = {"doc_id": "policy-refund-v4", "anchor": "2.3", "note": "运费由商家承担"}
    ref_json = json.dumps(ref, ensure_ascii=False)
    ref_bytes = len(ref_json.encode("utf-8"))
    print(f"    {ref_json}")
    print(f"    {ref_bytes} 字节 —— 相比一条 {avg:.0f} 字节的原文，省 {1 - ref_bytes / avg:.0%}")


def demo_growth() -> None:
    print()
    print(DPRINT)
    print("② 三种保留策略下，检查点怎么长")
    print(DPRINT)

    avg_fact = 123  # 字节，① 实测的平均值（不是估的）
    steps = [10, 25, 50, 100, 200]

    print("  场景：一个长任务，每步产出一条 fact。")
    print(f"  单条 fact = {avg_fact} 字节（含 JSON 开销）")
    print()
    print(f"  {'步数':<8} {'全量':<14} {'滚动窗口(10)':<16} {'摘要+引用(10+摘要)':<22}")
    print(f"  {'-' * 8} {'-' * 14} {'-' * 16} {'-' * 22}")

    for n in steps:
        full = n * avg_fact
        window = min(n, 10) * avg_fact
        # 摘要 + 引用：保留 10 条原文 + 1 段 400 字摘要 + 引用列表
        summary = 400 * 3
        refs = min(n, 30) * 60
        hybrid = min(n, 10) * avg_fact + (summary + refs if n > 10 else 0)
        print(f"  {n:<8} {full:>10,} B  {window:>12,} B  {hybrid:>18,} B")

    print()
    print("  ---- 全量在 200 步时是 24,600 字节（约 24 KB），单次看起来完全无害。")
    print("       真正的坑是**每一步都写一遍全量 State**，累计写入被放大（见下表）。")
    print()
    print("  真实的坑不在单次大小，在**写入放大**（每一步都写一遍全量）：")
    for n in (50, 200):
        full_writes = sum(i * avg_fact for i in range(1, n + 1))
        hybrid_writes = sum(
            min(i, 10) * avg_fact + (1000 + 1800 if i > 10 else 0)
            for i in range(1, n + 1)
        )
        gain = 1 - hybrid_writes / full_writes
        tag = f"省 {gain:.0%}" if gain > 0 else f"反而多 {abs(gain):.0%}"
        print(f"    {n:>3} 步：全量累计写 {full_writes / 1e6:>7.2f} MB，"
              f"摘要+引用累计写 {hybrid_writes / 1e6:>6.2f} MB，"
              f"{tag}")


def demo_deserialize_cost() -> None:
    print()
    print(DPRINT)
    print("③ 反序列化时间：恢复慢的真正原因")
    print(DPRINT)

    print("  恢复长任务时要做的事：读文件 -> json.loads -> 重建 State -> 找断点")
    print("  这里实测 json.loads 的耗时（不包含读盘，因为读盘受系统影响大）")
    print()

    payloads = []
    for n in (10, 50, 200, 1000):
        state = {
            "goal": "处理一批退款申请",
            "facts": SAMPLE_FACTS * (n // len(SAMPLE_FACTS) + 1),
            "errors": [],
            "refs": [{"doc": f"d{i}", "anchor": str(i)} for i in range(n)],
            "plan": [f"step {i}" for i in range(n)],
        }
        state["facts"] = state["facts"][:n]
        payloads.append((n, json.dumps(state, ensure_ascii=False)))

    print(f"  {'fact 条数':<12} {'JSON 字节':<12} {'loads 耗时':<14} {'相对 10 条':<12}")
    print(f"  {'-' * 12} {'-' * 12} {'-' * 14} {'-' * 12}")
    base = None
    for n, text in payloads:
        raw = text.encode("utf-8")
        # 跑 20 次取中位数，避免单次抖动
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            json.loads(text)
            times.append(time.perf_counter() - t0)
        times.sort()
        med = times[len(times) // 2] * 1000
        if base is None:
            base = med
        print(f"  {n:<12} {len(raw):<12,} {med:<14.3f} {med / base:<12.1f}x")

    print()
    print("  ---- 注意单位是**毫秒**，而且在纯 CPU 上是线性的。")
    print("       看起来无害？把它放到真实场景：")
    print("       · 你的长任务有 50 个并发，每次恢复都要 loads 一次")
    print("       · 每次恢复还可能要扫多个历史检查点找最新可用的那个")
    print("       · 加起来就是「重启后服务变慢 30 秒」的来源")
    print()
    print("  所以裁剪不只是省磁盘，更是省**恢复时间**。")


def demo_what_you_lose() -> None:
    print()
    print(DPRINT)
    print("④ 裁剪的代价：你丢掉了什么")
    print(DPRINT)

    print("  三种策略能回答什么问题：")
    print()
    print(f"  {'问题':<34} {'全量':<8} {'窗口10':<8} {'摘要+引用':<10}")
    print(f"  {'-' * 34} {'-' * 8} {'-' * 8} {'-' * 10}")
    rows = [
        ("第 2 步发现了什么？", "✅", "❌", "✅（摘要里）"),
        ("第 2 步的原文引用是什么？", "✅", "❌", "✅（引用表）"),
        ("最近 10 步的完整细节？", "✅", "✅", "✅"),
        ("一共走了多少步？", "✅", "❌", "✅（计数器）"),
        ("中间有哪些失败重试过？", "✅", "部分", "✅（errors 不裁）"),
        ("检查点多大？", "大", "小", "中"),
        ("恢复多快？", "慢", "快", "较快"),
    ]
    for q, a, b, c in rows:
        print(f"  {q:<34} {a:<8} {b:<8} {c:<10}")

    print()
    print("  ---- 注意「摘要+引用」在两个地方是全量比不了的：")
    print("     它比全量**小**，但比窗口**知道得多**。")
    print("     代价是：摘要是一次模型调用（要钱），而且摘要会丢细节。")
    print()
    print("  一个必须知道的分界：")
    print("   · **errors 永不裁剪**。冲突和失败是最终答案质量的证据（23.5 讲过）。")
    print("   · **用户明确说过的事实永不裁剪**。给它们打标记，进单独的槽位（第 26 章）。")
    print("   · 其余按窗口滚动。")
    print()
    print("  这三条的实际含义：你的裁剪规则不是「留最近 N 条」，")
    print("  而是「三类分别处理」。下面这个函数就是它的最小实现：")


def trim_policy() -> str:
    """本章推荐的裁剪策略（可直接抄）。返回示意代码，便于文档引用。"""
    return (
        "def trim(facts: list[Fact], window: int = 10) -> list[Fact]:\n"
        "    kept = [f for f in facts if f.pinned]        # ① 打标记的永不裁\n"
        "    rest = [f for f in facts if not f.pinned]\n"
        "    return kept + rest[-window:]                 # ② 其余滚动\n"
        "    # ③ errors 单独一个字段，从不经过这里"
    )


def demo_final() -> None:
    print()
    print(DPRINT)
    print("本章推荐的裁剪策略（可直接抄）")
    print(DPRINT)
    for line in trim_policy().split("\n"):
        print("  " + line)
    print()
    print("  为什么不是简单的 `facts[-10:]`：")
    print("   · 用户在第 2 步说的「我是企业版客户」如果被裁掉，")
    print("     第 50 步回答资质相关问题就会答错。")
    print("   · 这条事实的重要性与「新旧」无关，所以必须有 pinned 机制。")
    print()
    print("  一个判断 pinned 的实用规则（按成本从低到高）：")
    print("   1. 用户原话里出现「我的/我是/我们公司/记住」-> pinned")
    print("   2. 含实体标识（订单号/合同号/手机号）-> pinned")
    print("   3. 被后续步骤引用过 ≥ 2 次 -> pinned")
    print("   4. 以上都不满足，靠窗口滚动")


if __name__ == "__main__":
    demo_fact_weight()
    demo_growth()
    demo_deserialize_cost()
    demo_what_you_lose()
    demo_final()
    print()
    print(DPRINT)
    print("step6 完成。四句话带走：")
    print("  1. 中文最多 1 字符 = 3 字节（本样本实测平均 2.6 倍）。用 len(str) 估会低估。")
    print("  2. 单次大小不是问题，**写入放大**才是：200 步全量累计写 2.47 MB。")
    print("  3. 摘要+引用的收益随步数增长：50 步时反而略亏（摘要本身要钱），")
    print("     200 步时省 69% —— **短任务不要用摘要，长任务才值**。")
    print("  3. 裁剪省的不只是磁盘，更是恢复时间（json.loads 随条目线性增长）。")
    print("  4. 裁剪规则不是「留最近 N 条」，而是「打标记的 + 滚动的 + errors 不裁」。")
    print(DPRINT)
