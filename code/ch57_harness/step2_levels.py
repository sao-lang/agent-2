"""第 57 章 step2：缺一项就掉级——为什么不能用平均分（离线）。

运行：
    python code/ch57_harness/step2_levels.py

上一级的痛点：知道"能答四个问题"，但不知道"我现在是 L 几、下一级缺什么"。

这一级做什么：用 `MaturityAssessment` 算三个"看起来很强"的系统，
证明等级是"全部满足"，不是"平均分"——因为缺的那一项，正好是出事的那一项。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.harness import (  # noqa: E402
    CAPABILITIES,
    LEVEL_REQUIRES,
    LEVELS,
    MaturityAssessment,
)

# 三个候选系统的能力集合（key 见 common/harness.py 的 CAPABILITIES）
CASES = {
    "A 刚跑通 demo": {"trace"},
    "B 有观测、有护栏，唯独没做幂等": {
        "trace", "meter", "audit",
        "perm", "sandbox", "hitl", "budget_brake", "retry", "durable",
    },
    "C 什么都有，就是没接 CI 门禁": {
        "trace", "meter", "audit",
        "perm", "sandbox", "hitl", "budget_brake", "retry", "durable",
        "idempotent", "eval_set", "trajectory_eval", "stability",
        "cost_attribution", "three_level_budget", "cache", "wiki", "conflict", "injection",
        "context_budget", "memory_layers",
    },
}


def main() -> None:
    print("=" * 80)
    print("三个系统，三种成熟度")
    print("=" * 80)
    print(f"{'系统':<30}{'能力数':>6}{'等级':>6}  名称")
    print("-" * 80)
    for name, have in CASES.items():
        a = MaturityAssessment(have=have)
        lv = a.level()
        print(f"{name:<30}{len(have):>6}{'L' + str(lv) if lv else '<L1':>6}  "
              f"{LEVELS[lv][0] if lv else '未达标'}")

    print("\n" + "=" * 80)
    print("关键：为什么 B 和 C 不能用平均分救回来")
    print("=" * 80)
    for name in ("B 有观测、有护栏，唯独没做幂等", "C 什么都有，就是没接 CI 门禁"):
        a = MaturityAssessment(have=CASES[name])
        gaps = a.next_level_gaps()
        print(f"\n  【{name}】")
        for c in gaps[:3]:
            print(f"    · 缺「{c.name}」")
            print(f"       不做会：{c.why}")
            print(f"       怎么验：{c.probe}")

    b_lv = MaturityAssessment(have=CASES["B 有观测、有护栏，唯独没做幂等"]).level()
    c_lv = MaturityAssessment(have=CASES["C 什么都有，就是没接 CI 门禁"]).level()
    print(f"\n  👉 B 具备 {len(CASES['B 有观测、有护栏，唯独没做幂等'])}/{len(CAPABILITIES)} 项，"
          f"却停在 L{b_lv}；C 具备 21/22 项，也只到 L{c_lv}。")
    print("     因为'缺幂等'意味着：服务重启一次就重复退款一次；")
    print("     '缺 CI 门禁'意味着：下一次改动把质量改坏了，也没人拦。")
    print("     这类事故**一次就够毁掉整个项目**，不能用'其他 N 项都很好'抵消。")

    print("\n" + "=" * 80)
    print("等级是怎么算的（代码只有 8 行）")
    print("=" * 80)
    print("""    def level(self) -> int:
        lvl = 0
        for lv in sorted(LEVEL_REQUIRES):
            if all(k in self.have for k in LEVEL_REQUIRES[lv]):
                lvl = lv
            else:
                break          # ← 有一项不满足就停在这一级
        return lvl""")
    print("\n  每一级的要求：")
    for lv, keys in sorted(LEVEL_REQUIRES.items()):
        print(f"    L{lv}（{LEVELS[lv][0]}）：{len(keys)} 项 —— {', '.join(keys)}")

    print("\n" + "=" * 80)
    print("反模式：做了能力，没做'验证能力是否有效'的那一半")
    print("=" * 80)
    from common.harness import check_antipatterns

    demo_sets = {
        "只有 trace": {"trace"},
        "有护栏没回滚": {"hitl"},
        "有缓存没评测": {"cache"},
    }
    for name, have in demo_sets.items():
        for msg in check_antipatterns(have):
            print(f"  【{name}】{msg}")

    print("\n  六个反模式的共同结构：**做了能力，没做验证。**")
    print("  判据：每个能力都要配一个'我怎么知道它有效'的机制（就是每个 Capability 的 probe）。")

    print("\n" + "=" * 80)
    print("下一级：等级是自评，自评会骗自己——去代码里找证据")
    print("=" * 80)


if __name__ == "__main__":
    main()
