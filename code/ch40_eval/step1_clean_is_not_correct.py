"""第 40 章 step1：同一批"全对"的答案，为什么三种报法给出三种结论（离线）。

运行：
    python code/ch40_eval/step1_clean_is_not_correct.py

上一级的痛点：无（这是起点）。
这一级做什么：造三种运行（理想 / 答案对但绕远路 / 工具挂但答案瞎编），
然后用三种"报法"分别算一遍：

  报法 A：只报准确率          → 看起来 100%，其实一半是坏的
  报法 B：准确率 + 轨迹干净率  → 能看出"路走歪了"
  报法 C：A + B + 成本         → 能看出"路走歪了"要花多少钱

这一级要证明的只有一句话：
**"答案对"不是"做对了"，只是"这次蒙对了"之一。**
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.agent_eval import (  # noqa: E402
    AgentCase,
    AgentReport,
    AgentRun,
    TraceStep,
    score_result,
    score_trajectory,
)

CASES = [
    AgentCase("c1", "退款几天内可申请？", ["7 天"], expected_tools=["search_policy"], max_steps=4),
    AgentCase("c2", "会员退货优惠券返还吗？", ["不返还"], expected_tools=["search_policy", "get_order"], max_steps=4),
    AgentCase("c3", "换新流程多久？", ["5 到 7 个工作日"], expected_tools=["search_policy"], max_steps=4),
    AgentCase("c4", "客服电话？", ["400-800-1234"], expected_tools=["search_policy"], max_steps=4),
]


def st(i: int, kind: str, name: str = "", args: dict | None = None, err: str | None = None) -> TraceStep:
    return TraceStep(idx=i, kind=kind, name=name, args=args or {}, error=err)


def ideal(c: AgentCase) -> AgentRun:
    """理想：规划 → 一次检索 → 回答。"""
    return AgentRun(
        case_id=c.id, question=c.question, answer="；".join(c.must_contain) + "。",
        steps=[st(0, "plan"), *[st(1 + i, "tool", t, {"q": c.question}) for i, t in enumerate(c.expected_tools)],
               st(9, "model", "answer")],
        cost=0.006, latency_ms=1200,
    )


def wasteful(c: AgentCase) -> AgentRun:
    """答案对，但重复检索 3 次 + 4 次反思。"""
    return AgentRun(
        case_id=c.id, question=c.question, answer="；".join(c.must_contain) + "。",
        steps=[st(0, "plan"), *[st(1 + i, "tool", c.expected_tools[0], {"q": c.question}) for i in range(3)],
               *[st(4 + i, "model", "reflect") for i in range(4)], st(9, "model", "answer")],
        cost=0.021, latency_ms=6400,
    )


def lucky(c: AgentCase) -> AgentRun:
    """工具全挂了，模型凭先验"蒙对"了答案。

    这是最危险的一种：准确率看起来没问题，但功能其实已经废了。
    """
    return AgentRun(
        case_id=c.id, question=c.question, answer="；".join(c.must_contain) + "。",
        steps=[st(0, "plan"), st(1, "tool", c.expected_tools[0], {"q": c.question}, err="HTTP 503"),
               st(2, "model", "answer")],
        cost=0.004, latency_ms=900,
    )


def report(mk) -> AgentReport:
    rows = []
    for c in CASES:
        run = mk(c)
        rows.append((c, run, score_result(run, c), score_trajectory(run, c)))
    return AgentReport(rows)


def show(title: str, rep: AgentReport) -> None:
    s = rep.summary()
    print(f"\n{title}")
    print(f"  准确率 {s['pass_rate']:.0%}   轨迹干净率 {s['trajectory_clean_rate']:.0%}   "
          f"平均步数 {s['avg_steps']:.1f}   重复调用 {s['duplicate_calls']:.0f}   "
          f"平均成本 ¥{s['avg_cost']:.4f}")


def main() -> None:
    print("=" * 78)
    print("三种运行，三份报表")
    print("=" * 78)

    print(f"\n{'case':<6}{'期望答案':<20}{'理想':>6}{'绕远路':>8}{'蒙对':>6}")
    print("-" * 48)
    for c, a, b, d in zip(CASES, report(ideal).results, report(wasteful).results, report(lucky).results):
        print(f"{c.id:<6}{'；'.join(c.must_contain):<20}"
              f"{'OK' if a[2]['passed'] else 'NG':>6}{'OK' if b[2]['passed'] else 'NG':>8}"
              f"{'OK' if d[2]['passed'] else 'NG':>6}")

    ideal_rep = report(ideal)
    wasteful_rep = report(wasteful)
    lucky_rep = report(lucky)

    show("【报法 A】只看准确率（很多人只做这一步）", ideal_rep)
    show("", wasteful_rep)
    show("", lucky_rep)
    print("\n  👉 三份报表的准确率都是 100%。**只看这一列，你分不出哪个系统是好的。**")

    print("\n" + "=" * 78)
    print("【报法 B】加上轨迹：步数 / 重复 / 工具错误")
    print("=" * 78)
    for name, rep in (("理想", ideal_rep), ("绕远路", wasteful_rep), ("工具挂但蒙对", lucky_rep)):
        s = rep.summary()
        print(f"  {name:<14}轨迹干净率 {s['trajectory_clean_rate']:>4.0%}   "
              f"平均步数 {s['avg_steps']:>4.1f}  重复 {s['duplicate_calls']:.0f}  "
              f"超预算用例 {s['over_budget_cases']:.0f}")
    print("\n  👉 现在能分出'绕远路'了。但'工具挂但蒙对'看起来还不错——")
    print("     它的步数甚至更少（因为一次就放弃了）。**这就是轨迹层的盲区。**")

    print("\n" + "=" * 78)
    print("【报法 C】再看失败清单，而不是只看总分")
    print("=" * 78)
    fails = lucky_rep.failures()
    print(f"  工具挂但蒙对的失败清单：{len(fails)} 条")
    for c, run, rs, ts in fails:
        print(f"    {c.id}  答案{'对' if rs['passed'] else '错'}  "
              f"工具错误 {ts['tool_errors']} 次  缺工具 {ts['missing_tools']}")
    print("\n  👉 正确结论：'功能不可用，但答案碰巧对'。")
    print("     如果线上监控只看准确率，这次故障**永远不会被发现**。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  · 准确率回答的是'用户拿到的东西对不对'")
    print("  · 轨迹回答的是'系统是不是按设计在工作'")
    print("  · 失败清单回答的是'哪里正在坏，但还没坏到用户能察觉'")
    print("\n  三个都要。只报准确率的团队，会在半年后发现'成本莫名涨 3 倍'。")
    print("\n  下一级：这三层之外还有一个更危险的信号——")
    print("  同一个问题跑 5 次，通过率 80%。它既不是好也不是坏，是**最伤信任**的那种。")


if __name__ == "__main__":
    main()
