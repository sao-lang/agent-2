"""第 35 章示例：成本工程的四个杠杆（不需要 API）。

运行：
    python code/ch34_cost/demo_cost.py

四个杠杆，按收益从高到低：
  L1 缓存（精确 + 语义）
  L2 模型路由（简单任务用便宜模型）
  L3 上下文裁剪（第 43 章）
  L4 预算硬上限（第 58 章）

本示例用"模拟调用"来量化每个杠杆的收益，保证结果可复现。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cost import (  # noqa: E402
    BudgetManager,
    BudgetScope,
    CostBreakdown,
    ExactCache,
    ModelRouter,
    SemanticCache,
)
from common.meter import CallRecord  # noqa: E402


def mk(stage: str, model: str, tin: int, tout: int) -> CallRecord:
    return CallRecord(model=model, input_tokens=tin, output_tokens=tout, step=stage)


def main() -> None:
    # ---------------------------------------------------------------- 归因
    print("=" * 72)
    print("① 分项归因：钱花在哪个环节")
    print("=" * 72)

    flow = [
        mk("intent", "deepseek-chat", 300, 30),
        mk("retrieve-query-rewrite", "deepseek-chat", 400, 60),
        mk("plan", "deepseek-chat", 1200, 300),
        mk("answer", "deepseek-chat", 4000, 800),
        mk("reflect", "deepseek-chat", 5000, 600),   # 反思很贵：要带着全文
        mk("answer-retry", "deepseek-chat", 4500, 900),
    ]
    b = CostBreakdown()
    for r in flow:
        b.add(r)
    print(b.report())

    print("\n  👉 读法：")
    print("     · 'reflect' 一次就占了很大比例 —— 反思必须限制轮数（第 34 章）")
    print("     · 'answer-retry' 是重复花费 —— 说明第一次 output 被截断了（第 43 章）")
    print("     · 归因的目标不是'算出总数'，是'找到可以砍的那一块'")

    # ---------------------------------------------------------------- 缓存
    print("\n" + "=" * 72)
    print("② 缓存：最高性价比的杠杆")
    print("=" * 72)

    exact = ExactCache()
    questions = ["退货政策是什么？"] * 6 + ["运费怎么算？", "发票怎么开？", "会员有什么权益？"]
    for q in questions:
        hit = exact.get(q, "deepseek-chat")
        if hit is None:
            exact.put(q, "deepseek-chat", f"<答案:{q}>")
    print(f"  精确缓存：{len(questions)} 次请求，命中 {exact.hits} 次，命中率 {exact.hit_rate:.0%}")

    sem = SemanticCache(threshold=0.75)
    sem_questions = [
        "退货政策是什么？",
        "退货政策是什么？",       # 完全相同
        "请问退货政策是什么",     # 少标点
        "退货政策有哪些？",       # 近义
        "运费怎么计算？",         # 不同问题
        "发票怎么开？",
    ]
    print("\n  语义缓存（阈值 0.75，教学用近似相似度）：")
    for q in sem_questions:
        r = sem.get(q)
        if r:
            ans, score = r
            print(f"    ✅ 命中（相似度 {score:.2f}）{q}  →  {ans}")
        else:
            sem.put(q, f"<答案:{q}>")
            print(f"    ✎ 未命中，已缓存   {q}")

    print(f"\n  命中率：{sem.hits / (sem.hits + sem.misses):.0%}")
    print("\n  ⚠️ 语义缓存是一个**高风险优化**：")
    print("     · 阈值 0.92 以上才安全；0.75 会把'退货政策'和'换新政策'混起来")
    print("     · 只适合答案稳定的场景（政策/FAQ），不适合实时数据（库存/余额）")
    print("     · 上线前必须用评测集验证'命中后的答案是否正确'（第 28 章）")

    # ---------------------------------------------------------------- 路由
    print("\n" + "=" * 72)
    print("③ 模型路由：简单活别用贵模型")
    print("=" * 72)
    router = ModelRouter(cheap="deepseek-chat", default="deepseek-chat", strong="deepseek-reasoner")

    stages = [
        ("intent-classify", 300, 30),
        ("query-rewrite", 400, 60),
        ("answer", 4000, 800),
        ("plan", 1200, 300),
    ]
    print(f"  {'环节':<18}{'选用模型':<20}{'全用 strong':>12}{'路由后':>10}{'节省':>10}")
    print("  " + "-" * 72)
    total_strong = total_routed = 0.0
    for stage, tin, tout in stages:
        model, why = router.pick(stage)
        c = router.compare_cost(stage, tin, tout)
        total_strong += c["all_strong"]
        total_routed += c["routed"]
        print(f"  {stage:<18}{model:<20}{c['all_strong']:>12.6f}{c['routed']:>10.6f}{c['saved']:>10.6f}")
    print("  " + "-" * 72)
    print(f"  {'合计':<18}{'':<20}{total_strong:>12.6f}{total_routed:>10.6f}{total_strong - total_routed:>10.6f}")
    print(f"\n  路由节省：{(1 - total_routed / total_strong):.0%}")

    print("\n  👉 注意：这里'cheap'和'default'是同一个模型（默认配置）。")
    print("     真实场景请把 cheap 设成更便宜的模型（如 qwen-turbo / 本地小模型），")
    print("     节省会从 'strong→default' 变成 'strong→cheap'，差距大得多。")

    # ---------------------------------------------------------------- 预算
    print("\n" + "=" * 72)
    print("④ 预算：三级闸门")
    print("=" * 72)
    bm = BudgetManager(
        request=BudgetScope("请求", limit=0.02),
        session=BudgetScope("会话", limit=0.15),
        tenant=BudgetScope("租户", limit=1.0),
    )
    spend_seq = [0.008, 0.009, 0.009, 0.008, 0.011]
    for i, c in enumerate(spend_seq, 1):
        ok, why = bm.check(c)
        if ok:
            bm.spend(c)
            print(f"  第 {i} 次花费 ¥{c:.3f} → 允许（请求剩余 ¥{bm.request.remaining:.3f}）")
        else:
            print(f"  第 {i} 次花费 ¥{c:.3f} → 拒绝：{why}")

    print(f"\n  快照：{bm.snapshot()}")

    print("\n" + "=" * 72)
    print("⑤ 四个杠杆的收益排序（经验值）")
    print("=" * 72)
    print("  L1 缓存       ：命中率 30~60% → 成本直接降 30~60%（最高性价比）")
    print("  L2 模型路由   ：简单任务占 60~80% → 整体降 40~70%")
    print("  L3 上下文裁剪 ：减少 input → 降 20~40%（且能提升质量，第 43 章）")
    print("  L4 预算上限   ：不省钱，但**防止单次事故**（价值最高）")
    print("\n  顺序建议：先做 L1 和 L4（便宜且立刻见效），再做 L2，最后精细化 L3。")
    print("\n  ⚠️ 所有优化都必须过评测（第 28/43 章）——")
    print("     '省了 40% 但准确率掉了 10 个点' 不是优化，是事故。")


if __name__ == "__main__":
    main()
