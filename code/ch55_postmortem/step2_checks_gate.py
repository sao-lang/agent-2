"""第 56 章 step2：把\"不合格\"做成一道能自动判的检查（离线）。

运行：
    python code/ch55_postmortem/step2_checks_gate.py

上一级的痛点：知道\"要有 span 和证据\"，但没人来检查，写的人自己说了算。

这一级做什么：用 `Postmortem.checks()` 给两份复盘打分，
然后演示"少写一样"会被拦住——这就是把规范从\"约定\"变成\"门禁\"。

五道检查：
  1. 五问齐全（哪一样最容易缺：怎么证明）
  2. 有 trace 证据（没有证据的根因不可信）
  3. 有行动项（每条带 owner + deadline + status）
  4. 有新增评测用例（没有它，三个月后会再犯）
  5. 失败类型已分类（否则修复方向不确定）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.postmortem import Evidence, FailureType, FiveQuestions, Postmortem  # noqa: E402


def vague() -> Postmortem:
    return Postmortem(
        title="Agent 回答错误",
        occurred_at="2026-10-12 14:03",
        detected_at="2026-10-12 14:40",
        resolved_at="2026-10-12 17:20",
        severity="P2",
        impact="部分用户",
        five=FiveQuestions(
            q1_how_much_worse="有些用户反馈不对",
            q2_which_step="应该是模型的问题",
            q3_root_cause="AI 不稳定",
            q4_fix="优化 prompt",
        ),
    )


def complete() -> Postmortem:
    return Postmortem(
        title="退款时效从 7 天变成回答 15 天（检索到过期文档）",
        occurred_at="2026-10-12 14:03",
        detected_at="2026-10-12 14:11",
        resolved_at="2026-10-12 15:02",
        severity="P1",
        impact="59 分钟内 230 次退款咨询中 31 次答错（13.5%）",
        failure_type=FailureType.RETRIEVAL,
        five=FiveQuestions(
            q1_how_much_worse="退款类准确率 96% → 86.5%（−9.5pp，n=230）",
            q2_which_step="retrieval，top-1 命中 2025-06 版旧文档 c8812",
            q3_root_cause="重建索引时旧版未剔除，相似度 0.94，元数据无 effective_date",
            q4_fix="加 effective_date 过滤；旧版标 archived 不进索引",
            q5_regression="新增 3 条回归用例 + CI 门禁：退款类准确率不低于 95%",
        ),
        evidence=[
            Evidence("trace", "run_id=9f3ac2e1", "retrieval span 命中 c8812"),
            Evidence("metric", "refund_accuracy", "14:00 起 0.96 → 0.865"),
        ],
        action_items=[
            {"action": "补 effective_date", "owner": "wang", "due": "2026-10-15", "status": "done"},
            {"action": "索引剔除 archived", "owner": "li", "due": "2026-10-16", "status": "doing"},
        ],
        new_eval_cases=["退款几天内可申请", "旧版政策是否还会被召回"],
    )


def mutate(base: Postmortem, **changes) -> Postmortem:
    """复制一份再改一处，用来演示\"少写一样\"的后果。"""
    import copy

    m = copy.deepcopy(base)
    for k, v in changes.items():
        setattr(m, k, v)
    return m


def report(name: str, pm: Postmortem) -> dict:
    c = pm.checks()
    print(f"\n【{name}】{'✅ 通过' if c['ok'] else '❌ 未通过'}"
          f"   MTTD {c['mttd_min']} 分钟 / MTTR {c['mttr_min']} 分钟")
    print(f"  五问完整度：{pm.five.completeness():.0%}"
          f"{'' if not pm.five.missing() else '  缺：' + '、'.join(pm.five.missing())}")
    for p in c["problems"]:
        print(f"    · {p}")
    return c


def main() -> None:
    print("=" * 80)
    print("两份复盘，同一道门禁")
    print("=" * 80)
    report("含糊版", vague())
    report("完整版", complete())

    print("\n" + "=" * 80)
    print("从完整版出发，每少写一样，会发生什么")
    print("=" * 80)
    base = complete()
    mutations = {
        "把'怎么证明'清空": {"five": FiveQuestions(
            q1_how_much_worse=base.five.q1_how_much_worse,
            q2_which_step=base.five.q2_which_step,
            q3_root_cause=base.five.q3_root_cause,
            q4_fix=base.five.q4_fix,
            q5_regression="",
        )},
        "删掉 trace 证据": {"evidence": [e for e in base.evidence if e.kind != "trace"]},
        "行动项没有 owner": {"action_items": [{"action": "补 effective_date", "due": "2026-10-15", "status": "todo"}]},
        "没有新增评测用例": {"new_eval_cases": []},
        "分类写成 UNKNOWN": {"failure_type": FailureType.UNKNOWN},
    }
    for label, changes in mutations.items():
        report(label, mutate(base, **changes))

    print("\n" + "=" * 80)
    print("结论：五道检查各自在防什么")
    print("=" * 80)
    print("  五问齐全    → 防'只写自己知道的部分'（最容易漏的是'怎么证明'）")
    print("  trace 证据  → 防'猜根因'（没有证据的根因，换个时间就站不住）")
    print("  行动项      → 防'修了但没人跟'（owner + deadline 才叫行动项）")
    print("  评测用例    → 防'同一个故障三个月后再来一次'")
    print("  失败分类    → 防'诊断错了科室'（分类错 → 修复方向错）")

    print("\n  ⚠️ 注意：这些检查只能拦住'漏写'，拦不住'写错'。")
    print("     写错的那类（比如把 retrieval 问题写成 model 问题），需要人复查。")
    print("     所以门禁之后还要有一次 15 分钟的复查会——门禁管格式，人管判断。")


if __name__ == "__main__":
    main()
