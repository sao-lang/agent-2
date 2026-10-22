"""第 8 章示例：一个必然失败的步骤，三种策略分别怎么救（不需要 API）。

运行：
    python code/ch08_replan/demo_replan.py

场景：
  s1 查竞品A  ✅
  s2 查竞品B  ❌（工具不存在 → 需要 patch）
  s3 对比     依赖 s1+s2（s2 修好后才能跑）
  s4 给出建议  依赖 s3

对比：
  · 无重规划   → 卡死（s3、s4 永远等不到 s2）
  · RETRY      → 重试 2 次后仍然失败（因为工具名就是错的）
  · PATCH      → 只换掉 s2，s1 的结果保留，s3/s4 正常完成
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.planning import Executor, Plan, PlanStep, StepStatus  # noqa: E402
from common.replanning import ReplanSignal, ReplanningExecutor, fix_deadlock  # noqa: E402


def build_broken_plan() -> Plan:
    """故意让 s2 用一个不存在的动作名。"""
    return Plan(
        goal="对比三家竞品定价并给出建议",
        steps=[
            PlanStep(id="s1", goal="查竞品A定价", action="search", args={"q": "竞品A"}),
            PlanStep(id="s2", goal="查竞品B定价", action="search_B", args={"q": "竞品B"}),  # ← 错
            PlanStep(id="s3", goal="对比A与B", action="compare",
                     args={"a": "{s1.result}", "b": "{s2.result}"}, depends_on=["s1", "s2"]),
            PlanStep(id="s4", goal="给出建议", action="answer",
                     args={"summary": "{s3.result}"}, depends_on=["s3"]),
        ],
    )


def repair(plan: Plan, failed: PlanStep, action: str) -> list[PlanStep]:
    """"重规划"在教学版里用一个规则函数代替模型。

    真实系统里这一步是：把"计划 + 失败原因 + 工具清单"发给模型，
    让它重新生成失败的这一段（见 demo_replan_llm.py）。
    """
    return [
        PlanStep(
            id=failed.id,  # 保持 id 不变，下游引用才不会失效
            goal=failed.goal + "（已修正工具名）",
            action="search",
            args=failed.args,
            depends_on=failed.depends_on,
        )
    ]


TOOLS = {}


def main() -> None:
    from common.planning import TOOLS as REAL_TOOLS

    global TOOLS
    TOOLS = dict(REAL_TOOLS)

    print("=" * 68)
    print("对照组 1：没有任何重规划")
    print("=" * 68)
    p = Executor(tools=TOOLS).run(build_broken_plan())
    print(f"\n  完成：{p.is_complete()}  失败步骤：{[s.id for s in p.failed()]}")
    print("  剩余未执行：", [s.id for s in p.steps if s.status == StepStatus.PENDING])
    print("  👉 静默卡死：不报错，但 s3/s4 永远跑不了。这是 P&E 最危险的失败形态。")

    print("\n" + "=" * 68)
    print("对照组 2：只允许 RETRY（不许改计划）")
    print("=" * 68)
    p = ReplanningExecutor(
        tools=TOOLS,
        signal=ReplanSignal(max_retries_per_step=2, replan_budget=0),
        repair_fn=None,
    ).run(build_broken_plan())
    print(f"\n  完成：{p.is_complete()}  失败步骤：{[s.id for s in p.failed()]}")
    print("  👉 工具名根本不存在，重试多少次都没用。RETRY 只能治瞬时故障。")

    print("\n" + "=" * 68)
    print("实验组：PATCH（只替换失败步骤）")
    print("=" * 68)
    p = ReplanningExecutor(
        tools=TOOLS,
        signal=ReplanSignal(max_retries_per_step=2, replan_budget=2),
        repair_fn=repair,
    ).run(build_broken_plan())
    print(f"\n  完成：{p.is_complete()}")
    print(f"  计划版本：v{p.version}")
    print(f"  最终结果：{p.steps[-1].result}")
    print("\n  👉 s1 的结果**没有被重跑**——这就是 PATCH 的价值。")

    print("\n" + "=" * 68)
    print("依赖校验：让'静默卡死'变成'明确报错'")
    print("=" * 68)
    broken = Plan(
        goal="测试环依赖",
        steps=[
            PlanStep(id="a", goal="A", action="search", args={}, depends_on=["b"]),
            PlanStep(id="b", goal="B", action="search", args={}, depends_on=["a"]),
        ],
    )
    try:
        fix_deadlock(broken)
        print("  ❌ 没有检测出环（不应该）")
    except ValueError as e:
        print(f"  ✅ 正确报错：{e}")


if __name__ == "__main__":
    main()
