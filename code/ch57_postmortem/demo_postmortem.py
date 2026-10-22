"""第 56 章示例：把一次真实故障做成合格的复盘（不需要 API）。

运行：
    python code/ch56_postmortem/demo_postmortem.py

展示：
  1. 一份"不合格"的复盘（大多数人写成这样）
  2. 一份"合格"的复盘（可追溯、可执行）
  3. 自动体检报告
  4. 故障 → 评测用例的转换
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.postmortem import (  # noqa: E402
    Evidence,
    FailureType,
    FiveQuestions,
    Postmortem,
    classify,
    to_eval_case,
)


def bad_postmortem() -> Postmortem:
    return Postmortem(
        title="Agent 回答错误",
        occurred_at="2026-10-12 14:03",
        detected_at="2026-10-12 14:40",
        resolved_at="2026-10-12 17:20",
        severity="P2",
        impact="部分用户",
        failure_type=FailureType.UNKNOWN,
        five=FiveQuestions(
            q1_how_much_worse="有些用户反馈不对",
            q2_which_step="应该是模型的问题",
            q3_root_cause="AI 不稳定",
            q4_fix="优化 prompt",
        ),
    )


def good_postmortem() -> Postmortem:
    return Postmortem(
        title="退款时效从 7 天变成回答 15 天（检索到过期文档）",
        occurred_at="2026-10-12 14:03",
        detected_at="2026-10-12 14:11",
        resolved_at="2026-10-12 15:02",
        severity="P1",
        impact="14:03–15:02 共 59 分钟内，约 230 次退款咨询中 31 次给出错误时效（13.5%）",
        failure_type=FailureType.RETRIEVAL,
        five=FiveQuestions(
            q1_how_much_worse="退款类问题准确率从 96% 降到 86.5%（−9.5pp，n=230）",
            q2_which_step="retrieval 步骤，top-1 命中了 2025-06 版旧政策文档（chunk c8812）",
            q3_root_cause=(
                "10/12 14:00 部署时重新建索引，旧版文档未被剔除，"
                "且两版文本相似度 0.94，rerank 无法区分新旧；元数据里没有 effective_date"
            ),
            q4_fix="① 文档加 effective_date 元数据并做时间过滤；② 旧版标记 archived 不参与索引",
            q5_regression="新增 3 条回归用例（含'退款几天'），并加 CI 门禁：退款类准确率不低于 95%",
        ),
        evidence=[
            Evidence("trace", "run_id=9f3ac2e1", "retrieval span 命中 c8812，来源=policy_2025-06.pdf"),
            Evidence("metric", "refund_accuracy", "10/12 14:00 起从 0.96 掉到 0.865"),
            Evidence("reproduction", "tests/repro/refund_stale.py", "本地复现：能稳定召回旧文档"),
        ],
        action_items=[
            {"action": "文档元数据补 effective_date", "owner": "wang", "due": "2026-10-15", "status": "done"},
            {"action": "索引流水线剔除 archived 文档", "owner": "li", "due": "2026-10-16", "status": "doing"},
            {"action": "加 CI 门禁（退款类准确率 ≥95%）", "owner": "zhang", "due": "2026-10-18", "status": "todo"},
        ],
        new_eval_cases=[
            "退款几天内可申请",
            "无理由退货时效",
            "旧版政策是否还会被召回",
        ],
    )


def main() -> None:
    print("=" * 76)
    print("① 一份'不合格'的复盘（大多数人写成这样）")
    print("=" * 76)
    bad = bad_postmortem()
    c = bad.checks()
    print(bad.to_markdown())
    print(f"\n  体检结果：{'✅ 通过' if c['ok'] else '❌ 未通过'}")
    for p in c["problems"]:
        print(f"    · {p}")

    print("\n  👉 问题在哪：")
    print("     · 'AI 不稳定' 不是根因，是症状的同义反复")
    print("     · '应该是模型的问题' 是猜测，没有 trace 证据")
    print("     · '优化 prompt' 不可执行（改什么？怎么验证？）")
    print("     · 没有把故障变成评测用例 → **三个月后会再犯一次**")

    print("\n" + "=" * 76)
    print("② 一份'合格'的复盘")
    print("=" * 76)
    good = good_postmortem()
    print(good.to_markdown())
    c2 = good.checks()
    print(f"\n  体检结果：{'✅ 通过' if c2['ok'] else '❌ 未通过'}")
    print(f"  MTTD（发现耗时）：{c2['mttd_min']} 分钟")
    print(f"  MTTR（恢复耗时）：{c2['mttr_min']} 分钟")

    print("\n" + "=" * 76)
    print("③ 对比：合格的复盘多回答了哪三件事")
    print("=" * 76)
    rows = [
        ("变差多少", "有些用户反馈不对", "96% → 86.5%（−9.5pp，n=230）"),
        ("哪一步", "应该是模型的问题", "retrieval，top-1 命中旧文档 c8812"),
        ("为什么", "AI 不稳定", "旧文档未剔除 + 相似度 0.94 + 无 effective_date"),
        ("怎么修", "优化 prompt", "加元数据过滤 + 剔除 archived"),
        ("怎么证明", "（空）", "3 条回归用例 + CI 门禁 ≥95%"),
    ]
    print(f"  {'问题':<10}{'不合格':<26}{'合格'}")
    print("  " + "-" * 74)
    for q, a, b in rows:
        print(f"  {q:<10}{a:<26}{b}")

    print("\n" + "=" * 76)
    print("④ 自动分类：从症状猜类型（只给候选）")
    print("=" * 76)
    symptoms = [
        "用户问退款时效，答成了 15 天，但文档里写的是 7 天",
        "TOOL_ERROR: HTTP 503 工具调用失败",
        "429 rate limit exceeded",
        "回答被 BLOCKED，用户说这是正常问题",
        "token 超限，前面的对话被截断了",
        "模型编造了一个不存在的订单号",
    ]
    for s in symptoms:
        ft, conf = classify(s)
        print(f"  {ft.value:<10}({conf:.0%})  {s[:44]}")
        print(f"              → {ft.fix_direction}")

    print("\n  ⚠️ 自动分类只给候选，**必须人工确认**。")
    print("     注意第一条能命中 retrieval，是因为词表里有'文档里写的是'；")
    print("     一旦症状换一种说法（'答了个不知道'），分类器就退回 unknown。")
    print("     所以词表只能覆盖已经踩过的坑，新坑还是要人来看 trace。")
    print("     分类错了，修复方向就错了——你会去改 prompt，而真正的病根在索引。")

    print("\n" + "=" * 76)
    print("⑤ 最重要的一步：故障 → 评测用例")
    print("=" * 76)
    case = to_eval_case(good)
    print(f"  {case}")
    print("\n  👉 这一步没做，复盘就只是'事后写的一篇文章'。")
    print("     做了这一步，这个故障就**永远不会以同样的方式再来一次**。")

    print("\n" + "=" * 76)
    print("⑥ 复盘的三个反模式")
    print("=" * 76)
    print("  1. **归因于人**（'是张三上线忘了检查'）")
    print("     → 正确做法：问'为什么流程允许他这么做'")
    print("  2. **停在'已修复'**")
    print("     → 正确做法：加评测用例 + 加 CI 门禁")
    print("  3. **只写不复查**")
    print("     → 正确做法：行动项必须有 owner + deadline，两周后复查状态")

    print("\n" + "=" * 76)
    print("⑦ 一次故障的真正价值")
    print("=" * 76)
    print("  一次故障 = 一条新的评测用例 + 一条新的门禁 + 一个更清楚的边界认知")
    print("  这就是'工程能力'的来源：不是学了很多东西，而是每次出错都留下了防线。")


if __name__ == "__main__":
    main()
