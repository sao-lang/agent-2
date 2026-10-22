"""第 57 章示例：Harness 成熟度自评 + 反向索引（不需要 API）。

运行：
    python code/ch57_harness/demo_harness.py

它做四件事：
  1. 打印"六大能力域 × 章节"的完整回扣表（书末总结）
  2. 对本书的 code/ 目录做一次真实体检
  3. 演示 L1~L5 的成熟度评估（用 4 套不同的能力集合）
  4. 打印反模式检查结果
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.harness import (  # noqa: E402
    CAPABILITIES,
    LEVELS,
    MaturityAssessment,
    chapter_map_markdown,
    check_antipatterns,
    health_check,
)


def main() -> None:
    root = Path(__file__).resolve().parents[2]

    print("=" * 78)
    print("① 六大能力域 × 章节回扣表（这就是 Harness 的完整定义）")
    print("=" * 78)
    print(chapter_map_markdown())

    print("\n" + "=" * 78)
    print("② 对本书代码做一次真实体检")
    print("=" * 78)
    hc = health_check(root)
    print(f"  项目：{hc['root']}")
    print(f"  {'能力':<14}{'落地'}")
    print("  " + "-" * 26)
    for k, v in hc["found"].items():
        print(f"  {k:<14}{'✅' if v else '❌'}")
    print(f"\n  成熟度：L{hc['level']}（{hc['level_name']}）")
    if hc["gaps"]:
        print(f"  下一级还缺：{hc['gaps']}")

    print("\n  👉 这就是体检的价值：不是打分，是**去代码里找证据**。")
    print("     找不到 = 没有。'我记得我加过' 不算。")

    print("\n" + "=" * 78)
    print("③ 四个典型阶段的成熟度对比")
    print("=" * 78)
    personas = {
        "刚跑通 demo": {"trace"},
        "有观测但没护栏": {"trace", "meter", "audit", "eval_set", "trajectory_eval"},
        "有护栏但没回归": {"trace", "meter", "audit", "perm", "sandbox", "hitl",
                       "budget_brake", "retry", "durable"},
        "完整工程化": {c.key for c in CAPABILITIES},
    }
    print(f"  {'阶段':<20}{'等级':>6}  {'名称':<8}{'缺什么（通往下一级）'}")
    print("  " + "-" * 76)
    for name, have in personas.items():
        a = MaturityAssessment(have=have)
        gaps = [c.name for c in a.next_level_gaps()][:2]
        print(f"  {name:<20}{'L' + str(a.level()):>6}  {LEVELS.get(a.level(), ('<L1', ''))[0]:<8}"
              f"{', '.join(gaps) if gaps else '已到顶'}")

    print("\n  读法：")
    print("    · L2（可观测）：能看见问题，但拦不住")
    print("    · L3（受控）：拦得住了，但看不到'是不是变差了'")
    print("    · L4（可回归）：能证明没变差")
    print("    · L5（可运营）：能对业务方讲清楚成本/质量/时效")

    print("\n" + "=" * 78)
    print("④ 反模式检查")
    print("=" * 78)
    demos = [
        ("只有 trace 没有评测", {"trace", "meter", "audit"}),
        ("只有护栏没有回滚", {"perm", "hitl", "sandbox"}),
        ("只有缓存没有评测", {"cache", "meter"}),
        ("有预算但没归因", {"budget_brake", "perm"}),
    ]
    for name, have in demos:
        warns = check_antipatterns(have)
        print(f"\n  【{name}】")
        if warns:
            for w in warns:
                print(f"    {w}")
        else:
            print("    ✅ 未命中反模式")

    print("\n" + "=" * 78)
    print("⑤ 完整自评报告（示例：一个 L3 系统）")
    print("=" * 78)
    sample = {
        "trace", "meter", "audit",
        "perm", "sandbox", "hitl", "budget_brake", "retry", "durable",
        "context_budget",
    }
    print(MaturityAssessment(have=sample).report())

    print("\n" + "=" * 78)
    print("⑥ 一句话总结这本书")
    print("=" * 78)
    print("  Agent 的能力来自模型，Agent 的可靠性来自 Harness。")
    print("  全书讲的核心都是后者：")
    print("    边界（19/20/21）  仪表（1/2）  刹车（3/8/9）")
    print("    预算（22）  质量（37/38）  知识（11/17/18/24/25）")
    print("\n  你不需要记住每一章的细节，你只需要记住：")
    print("    · 任何一个 Agent 上线前，先问那四个问题（改完怎么证明？出错怎么定位？")
    print("      坏了怎么恢复？花了多少钱？）")
    print("    · 答不上来，就还没到能上线的程度。")


if __name__ == "__main__":
    main()
