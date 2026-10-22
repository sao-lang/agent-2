"""第 40 章示例：四层评测 + A/B 对比（不需要 API）。

运行：
    python code/ch38_eval/demo_agent_eval.py

用模拟的 Agent 运行数据演示：
  1. L1 结果评估 vs L2 轨迹评估（"答案对但路径蠢"的案例）
  2. L3 稳定性（同一问题跑 5 次，有几次对）
  3. L4 成本与延迟
  4. A/B 对比（一次只改一个变量）
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
    cost_latency,
    print_diff,
    score_result,
    score_trajectory,
    stability,
)


CASES = [
    AgentCase("c1", "退款几天内可申请？", ["7 天"], expected_tools=["search_policy"]),
    AgentCase("c2", "会员退货优惠券返还吗？", ["不返还"], expected_tools=["search_policy", "get_order"]),
    AgentCase("c3", "换新流程多久？", ["5 到 7 个工作日"], expected_tools=["search_policy"]),
    AgentCase("c4", "客服电话？", ["400-800-1234"], expected_tools=["search_policy"]),
]


def step(i: int, kind: str, name: str = "", args: dict | None = None, res: str = "", cost: float = 0.002, err=None):
    return TraceStep(idx=i, kind=kind, name=name, args=args or {}, result=res, cost=cost, tokens=300, error=err)


def good_run(case: AgentCase) -> AgentRun:
    """理想路径：规划 → 检索 → 回答。"""
    return AgentRun(
        case_id=case.id,
        question=case.question,
        answer="；".join(case.must_contain) + "。",
        steps=[
            step(0, "plan", "plan"),
            step(1, "tool", case.expected_tools[0], {"q": case.question}, "命中 2 条"),
            *[step(2 + i, "tool", t, {"q": case.question}, "命中 1 条") for i, t in enumerate(case.expected_tools[1:])],
            step(9, "answer", "answer"),
        ],
        cost=0.006,
        latency_ms=1200,
    )


def wasteful_run(case: AgentCase) -> AgentRun:
    """答案对，但路径蠢：重复检索 3 次 + 步数超预算。"""
    calls = [step(1 + i, "tool", case.expected_tools[0], {"q": case.question}, "命中 2 条") for i in range(3)]
    return AgentRun(
        case_id=case.id,
        question=case.question,
        answer="；".join(case.must_contain) + "。",   # 答案是对的
        steps=[
            step(0, "plan", "plan"),
            *calls,
            *[step(4 + i, "model", "reflect") for i in range(4)],   # 4 次反思
            step(9, "answer", "answer"),
        ],
        cost=0.021,
        latency_ms=6400,
    )


def broken_run(case: AgentCase) -> AgentRun:
    """工具报错。"""
    return AgentRun(
        case_id=case.id,
        question=case.question,
        answer="资料中未提及",
        steps=[step(1, "tool", "search_policy", {"q": case.question}, err="HTTP 503")],
        cost=0.003,
        latency_ms=800,
    )


def main() -> None:
    print("=" * 74)
    print("① L1 vs L2：答案对 ≠ 路径对")
    print("=" * 74)
    print(f"  {'case':<8}{'答案':>8}{'轨迹干净':>10}{'步数':>6}{'重复':>6}{'成本':>9}")
    print("  " + "-" * 52)
    for c in CASES:
        r = wasteful_run(c)
        rs = score_result(r, c)
        ts = score_trajectory(r, c)
        print(f"  {c.id:<8}{'✅' if rs['passed'] else '❌':>8}{'✅' if ts['clean'] else '❌':>10}"
              f"{ts['steps']:>6}{ts['duplicate_calls']:>6}{r.cost:>9.3f}")

    print("\n  👉 全部'答案正确'，但全部'轨迹脏'（重复调用 + 超预算）。")
    print("     只看 L1 你会以为系统很健康——实际成本是理想路径的 3.5 倍。")

    print("\n" + "=" * 74)
    print("② L3 稳定性：同一问题跑 5 次")
    print("=" * 74)
    c = CASES[1]
    mixed = [good_run(c), good_run(c), broken_run(c), good_run(c), wasteful_run(c)]
    st = stability(mixed, c)
    print(f"  case：{c.question}")
    print(f"  通过率：{st['pass_rate']:.0%}    一致性：{st['consistent']}    flaky：{st['flaky']}")
    print(f"  唯一答案数：{st['unique_answers']}")
    print("\n  👉 flaky=True 是**最危险的状态**：")
    print("     用户第一次成功、第二次失败，他会认为'这个系统不可靠'——")
    print("     而这种不可靠无法从单次评测里看出来。")

    print("\n" + "=" * 74)
    print("③ L4 成本与延迟")
    print("=" * 74)
    ideal = [good_run(c) for c in CASES]
    wasteful = [wasteful_run(c) for c in CASES]
    ci, cw = cost_latency(ideal), cost_latency(wasteful)
    print(f"  {'指标':<20}{'理想路径':>12}{'浪费路径':>12}{'倍数':>8}")
    print("  " + "-" * 54)
    for k in ("avg_cost", "p95_cost", "avg_latency_ms", "p95_latency_ms"):
        print(f"  {k:<20}{ci[k]:>12.3f}{cw[k]:>12.3f}{cw[k] / ci[k]:>8.1f}x")

    print("\n" + "=" * 74)
    print("④ A/B 对比：一次只改一个变量")
    print("=" * 74)

    exp_bad = Experiment(
        name="同时改 prompt 和模型",
        variable="prompt",
        baseline_config={"prompt": "v1", "model": "cheap", "chunk": 400},
        variant_config={"prompt": "v2", "model": "strong", "chunk": 400},
    )
    ok, why = exp_bad.validate()
    print(f"  '{exp_bad.name}' → {'✅ 合法' if ok else '❌ ' + why}")

    exp_good = Experiment(
        name="只改 prompt",
        variable="prompt",
        baseline_config={"prompt": "v1", "model": "cheap", "chunk": 400},
        variant_config={"prompt": "v2", "model": "cheap", "chunk": 400},
    )
    ok, why = exp_good.validate()
    print(f"  '{exp_good.name}' → {'✅ 合法' if ok else '❌ ' + why}")

    print("\n  👉 第一条实验是**无效的**：prompt 和 model 同时变了，")
    print("     你无法知道提升来自哪一个。这就是很多'优化'上线后无效的原因。")

    print("\n" + "=" * 74)
    print("⑤ 报表：基线 vs 当前（带方向判断）")
    print("=" * 74)
    base_report = AgentReport([(c, good_run(c), score_result(good_run(c), c), score_trajectory(good_run(c), c)) for c in CASES])
    cur_report = AgentReport(
        [(c, wasteful_run(c), score_result(wasteful_run(c), c), score_trajectory(wasteful_run(c), c)) for c in CASES]
    )
    print(print_diff(base_report, cur_report))

    print("\n  👉 注意 'pass_rate' 没变（都是 100%），但 'avg_cost' 涨了 3.5 倍。")
    print("     如果报表只报'准确率'，你会认为这次改动是'无变化'——")
    print("     实际上它让成本翻了三倍。")

    print("\n" + "=" * 74)
    print("⑥ 评测体系的价值：三个必须回答的问题")
    print("=" * 74)
    print("  1. 改了之后，完成率变了多少？（L1）")
    print("  2. 路径有没有变蠢？（L2：步数、重复、超预算）")
    print("  3. 稳不稳定？（L3：同一问题多跑几次）")
    print("\n  只回答第 1 个的团队，通常在半年后发现'成本莫名其妙涨了 3 倍'。")


if __name__ == "__main__":
    main()
