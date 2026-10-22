"""第 22 章 step1：账单涨了 3 倍，你能说清花在哪吗（离线）。

运行：
    python code/ch22_cost/step1_attribution.py

上一级的痛点：第 1 章教会你"记账"（记下每次调用花了多少），
             但记账只给你一个总数 —— 账单涨 3 倍时，这个总数回答不了"为什么"。
这一级做什么：把同一批调用按**环节**归因，让"哪一块该砍"自己浮出来。

关键：`CallRecord.step` 这个字段。没有它，你只有总额。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cost import CostBreakdown  # noqa: E402
from common.meter import CallRecord  # noqa: E402

# 模型档位 → 真实模型名（本仓库 meter 里的定价表）
MODEL = {"cheap": "qwen-plus", "default": "deepseek-chat"}

# 一次真实请求链路上的调用（数字取自本项目实测的量级）
# (环节, 模型, input_tokens, output_tokens, 是否重试)
CALLS = [
    ("intent", "cheap", 180, 30, False),
    ("retrieve-query-rewrite", "cheap", 260, 40, False),
    ("plan", "default", 900, 300, False),
    ("answer", "default", 3600, 600, False),
    ("reflect", "default", 5200, 200, False),
    ("answer-retry", "default", 4200, 600, True),   # ← 第一次被截断，重来一次
]


def make_record(stage: str, tier: str, tin: int, tout: int, retry: bool) -> CallRecord:
    # cost 是 CallRecord 的 property，由 model + tokens 自动算出，不用手填
    return CallRecord(
        model=MODEL[tier],
        step=stage,
        input_tokens=tin,
        output_tokens=tout,
        retries=1 if retry else 0,
    )


def main() -> None:
    bd = CostBreakdown()
    for stage, model, tin, tout, retry in CALLS:
        bd.add(make_record(stage, model, tin, tout, retry))

    print("=" * 66)
    print("按环节归因")
    print("=" * 66)
    print(bd.report())

    print("\n" + "=" * 66)
    print("★ 看占比，不要看绝对值")
    print("=" * 66)
    top = bd.top(3)
    for i, (stage, cost, ratio) in enumerate(top, 1):
        print(f"  第 {i} 贵：{stage:<24}{ratio:>6.0%}  ¥{cost:.6f}")

    print()
    print(f"  前三名合计占 {sum(r for _, _, r in top):.0%}，其余环节占 {1 - sum(r for _, _, r in top):.0%}。")

    print("\n" + "=" * 66)
    print("★ 三个立刻能读出来的结论")
    print("=" * 66)

    retry = bd.by_stage.get("answer-retry", 0.0)
    print(f"  ① 重试花了 ¥{retry:.6f}（{retry / bd.total:.0%}）")
    print("     重试 = 白花钱。它的根因通常是：")
    print("       · output 被 max_tokens 截断（第 11 章）")
    print("       · 被护栏拦了但没告诉用户（第 19 章）")
    print("     修掉重试的收益，通常比调任何 prompt 都大。")
    print()

    reflect = bd.by_stage.get("reflect", 0.0)
    answer = bd.by_stage.get("answer", 0.0)
    rel = "比正式回答还贵" if reflect > answer else ("和正式回答一样贵" if abs(reflect - answer) < 1e-9 else "比正式回答便宜")
    print(f"  ② 反思花了 ¥{reflect:.6f}（{reflect / bd.total:.0%}），{rel}（¥{answer:.6f}）")
    print("     第 7 章说过：反思要把全文再问一遍，input 成本翻倍 ——")
    print("     所以『反思』这一环几乎总是不成比例地贵。")
    print("     修法：限制轮数，或只对低置信度答案反思。")
    print()

    cheap_stages = [s for s, *_ in CALLS if not s.startswith(("answer", "reflect", "plan"))]
    cheap_cost = sum(bd.by_stage.get(s, 0.0) for s in set(cheap_stages))
    print(f"  ③ 前半段（intent + 改写）合计只占 {cheap_cost / bd.total:.0%}")
    print("     这恰恰是最容易被『顺手优化』的地方——因为规则简单、看起来可控。")
    print("     归因的第一个价值：**别在百分之一的地方花百分之八十的精力**。")

    print("\n" + "=" * 66)
    print("为什么必须按环节，而不是按模型")
    print("=" * 66)
    by_model: dict[str, float] = {}
    for r in bd.records:
        by_model[r.model] = by_model.get(r.model, 0.0) + r.cost
    print(f"  {'模型':<12}{'成本':>12}{'占比':>8}")
    print("  " + "-" * 34)
    for m, c in sorted(by_model.items(), key=lambda x: -x[1]):
        print(f"  {m:<12}{c:>12.6f}{c / bd.total:>7.0%}")
    print()
    print(f"  按模型看，你只知道『{max(by_model, key=by_model.get)} 花了 {max(by_model.values()) / bd.total:.0%}』—— 这句话没法行动。")
    print("  业务方问的是『聊天为什么比查询贵』，是**环节**的问题。")

    print("\n" + "=" * 66)
    print("结论")
    print("=" * 66)
    print("  成本工程四步：归因 → 控制 → 优化 → 报表。")
    print("  大多数人直接从『控制』开始（设个预算上限），")
    print("  结果就是：预算一超就停，但**不知道该改哪**。")
    print("  下一级做控制：三级预算闸门。")


if __name__ == "__main__":
    main()
