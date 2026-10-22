"""第 40 章 step3：三种"看起来是优化"的改动，只有一种真的变好了（离线）。

运行：
    python code/ch40_eval/step3_ab_and_report.py

上一级的痛点：拿到了四层指标，但不知道"该怎么比"。

这一级做什么：
  ① 同一个基线，做三次 A/B，每次只改一个变量 —— 并且**故意做错一次**
  ② 用带方向判断的报表把三次结果并排打出来
  ③ 展示一个真实会踩的坑：改了 2 个变量，结论作废

三次改动：
  甲、只换模型（便宜档），但没改 prompt        → 成本降、质量掉
  乙、只改 prompt（要求"简短回答"）             → 成本降、质量不掉
  丙、prompt + 模型一起换                       → 看起来最好，**但结论无效**
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.agent_eval import (  # noqa: E402
    AgentCase,
    AgentReport,
    AgentRun,
    Experiment,
    TraceStep,
    print_diff,
    score_result,
    score_trajectory,
)

CASES = [
    AgentCase("c1", "退款几天内可申请？", ["7 天"], max_steps=4),
    AgentCase("c2", "会员退货优惠券返还吗？", ["不返还"], max_steps=4),
    AgentCase("c3", "换新流程多久？", ["5 到 7 个工作日"], max_steps=4),
    AgentCase("c4", "客服电话？", ["400-800-1234"], max_steps=4),
]


def make_run(c: AgentCase, *, right: bool, cost: float, steps: int = 3) -> AgentRun:
    ans = "；".join(c.must_contain) + "。" if right else "资料中未提及，建议咨询客服。"
    return AgentRun(
        case_id=c.id, question=c.question, answer=ans,
        steps=[TraceStep(i, "model" if i == steps - 1 else "tool", "search_policy" if i else "plan")
               for i in range(steps)],
        cost=cost, latency_ms=900 + 100 * steps,
    )


def report(right_ratio: float, cost: float) -> AgentReport:
    """按"前 N 个正确"合成一份报表。"""
    n_right = round(right_ratio * len(CASES))
    rows = []
    for i, c in enumerate(CASES):
        r = make_run(c, right=i < n_right, cost=cost)
        rows.append((c, r, score_result(r, c), score_trajectory(r, c)))
    return AgentReport(rows)


def main() -> None:
    baseline = report(1.0, 0.0080)

    experiments = [
        ("甲：只换便宜模型", {"model": "cheap", "prompt": "v1"}, {"model": "mini", "prompt": "v1"}, "model",
         report(0.75, 0.0030), "成本降 62%，但 4 条里错了 1 条"),
        ("乙：只改 prompt 要求简短", {"model": "cheap", "prompt": "v1"}, {"model": "cheap", "prompt": "v2-short"}, "prompt",
         report(1.0, 0.0056), "成本降 30%，质量不变"),
        ("丙：prompt + 模型一起换", {"model": "cheap", "prompt": "v1"}, {"model": "mini", "prompt": "v2-short"}, "prompt",
         report(1.0, 0.0024), "看起来最好——但**无效**"),
    ]

    print("=" * 82)
    print("基线")
    print("=" * 82)
    print(f"  准确率 {baseline.summary()['pass_rate']:.0%}   平均成本 ¥{baseline.summary()['avg_cost']:.4f}")

    for name, base_cfg, var_cfg, variable, current, comment in experiments:
        exp = Experiment(name=name, variable=variable, baseline_config=base_cfg, variant_config=var_cfg)
        ok, why = exp.validate()
        print("\n" + "=" * 82)
        print(f"{name}   → {'✅ 实验有效' if ok else '❌ 实验无效：' + why}")
        print("=" * 82)
        print(print_diff(baseline, current))
        print(f"\n  {comment}")
        if not ok:
            print("  ⚠️ 因为同时改了 2 个变量，你无法判断收益来自哪一个。")
            print("     上线时只改 prompt，实际收益可能是 0——这就是'优化上线后无效'的典型路径。")

    print("\n" + "=" * 82)
    print("顺便看一个报表本身的坑：为什么'成本降 62%'能显示成'='")
    print("=" * 82)
    print("  avg_cost：0.0080 → 0.0030，绝对差 0.005。")
    print("  如果方向判断用绝对阈值 0.005，它会判成'＝'——完全错误。")
    print("  所以 print_diff 对成本/延迟用**相对阈值（5%）**，对比率类用绝对阈值。")
    print("  这条规则是本章修的一个真实 bug：旧版会在'成本翻倍'时显示'＝'。")

    print("\n" + "=" * 82)
    print("结论：三个数字，三种不同的'好'")
    print("=" * 82)
    print("  甲：成本 ↓  质量 ↓   → 这是**降级**，不是优化（除非你接受质量损失）")
    print("  乙：成本 ↓  质量 →   → 这是**真优化**")
    print("  丙：成本 ↓  质量 →   → 结论不可信，**重做实验**")
    print("\n  → 报表必须同时给出'方向'和'有效性'，否则你会把降级当成优化。")

    print("\n" + "=" * 82)
    print("下一级：这批评测集从哪来、怎么保证它不被'改卷'")


if __name__ == "__main__":
    main()
