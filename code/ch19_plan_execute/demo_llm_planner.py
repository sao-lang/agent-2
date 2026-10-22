"""第 19 章示例 2：用真实模型生成计划（需要 API key）。

运行：
    python code/ch19_plan_execute/demo_llm_planner.py

对比点：
  · 走一次 ReAct：模型一路往下走，走到哪算哪
  · 走一次 P&E  ：模型先输出完整计划（可审查），再执行

重点看 P&E 的计划**你能否一眼看懂并否决**——
这才是它最大的工程价值：把"模型要做的事"提前暴露给人类。

⚠️ 这是本书唯一"必须配 API key 才能跑"的第 19 章脚本。
   `demo_plan_exec.py` 已经覆盖了本章的全部核心（依赖、执行、并行），
   这个脚本只是演示"计划是模型生成的"这件事。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field  # noqa: E402

from common import get_settings, make_llm  # noqa: E402
from common.planning import TOOLS, Executor, Plan, PlanStep  # noqa: E402


class PlannedStep(BaseModel):
    """给模型看的输出结构。

    为什么要用 Pydantic 而不是让模型自由输出？
    因为计划是要**被机器执行**的：action 必须是已知工具，args 必须是 dict。
    自由文本你还要再解析一遍（第 17 章的教训）。
    """

    goal: str = Field(description="这一步要达成什么，一句话，面向人")
    action: str = Field(description=f"工具名，只能是：{', '.join(TOOLS)}")
    args: dict[str, Any] = Field(default_factory=dict, description="工具参数")
    depends_on: list[int] = Field(
        default_factory=list, description="依赖第几步（从 1 开始编号），没有依赖就留空"
    )


class PlannedSteps(BaseModel):
    steps: list[PlannedStep]


# ⚠️ 注意这里的 {{ }} —— 这是 f-string 的转义。
#    我第一版写成 "{sN.result}" 直接触发了 KeyError: 'sN'（它被当成占位符了）。
PLANNER_PROMPT = """你是任务规划器。请把用户目标拆成可执行步骤。

规则：
1. 步骤数量尽量少，能合并就合并
2. 独立的步骤不要互相依赖（这样能并行）
3. 需要前面结果时，在 args 里用字符串 "{{sN.result}}" 引用第 N 步
4. 必须有一步 action="answer" 作为最终产出

可用工具：{tools}
用户目标：{goal}"""


def plan_with_llm(goal: str) -> Plan:
    llm = make_llm()
    structured = llm.with_structured_output(PlannedSteps)
    result: PlannedSteps = structured.invoke(
        PLANNER_PROMPT.format(goal=goal, tools=", ".join(TOOLS))
    )

    steps = [
        PlanStep(
            id=f"s{i + 1}",
            goal=st.goal,
            action=st.action if st.action in TOOLS else "answer",
            args=st.args,
            depends_on=[f"s{d}" for d in st.depends_on],
        )
        for i, st in enumerate(result.steps)
    ]
    return Plan(goal=goal, steps=steps)


def review(plan: Plan) -> bool:
    """人工审查计划——这是 P&E 在生产里最值钱的一步。

    真实系统里这里会走 HITL（第 33 章）：把计划展示给用户，等确认。
    """
    print("\n=== 计划审查 ===")
    for step in plan.steps:
        deps = f" ← {step.depends_on}" if step.depends_on else ""
        print(f"  [{step.id}] {step.action}({json.dumps(step.args, ensure_ascii=False)[:60]}){deps}")
        print(f"       目标：{step.goal}")

    risky = [
        st for st in plan.steps
        if st.action == "answer" and not st.depends_on and len(plan.steps) > 1
    ]
    if risky:
        print("\n⚠️  警告：存在不依赖任何前置步骤的 answer，可能给出了没根据的结论。")
        return False
    return True


def main() -> None:
    s = get_settings()
    if s.api_key in ("missing", ""):
        print("❌ 需要 API key。请复制 .env-example 为 .env 并填入配置。")
        print("   如果只想跑离线部分，请用：python code/ch19_plan_execute/demo_plan_exec.py")
        return

    goal = "对比三家竞品定价，给出我方定价建议"
    print(f"目标：{goal}")

    plan = plan_with_llm(goal)
    if not review(plan):
        print("\n❌ 计划未通过审查，请修改 prompt 或模型后重试")
        return

    print("\n=== 执行 ===")
    plan = Executor(tools=TOOLS).run(plan)

    print(f"\n=== 结果 ===\n  {plan.steps[-1].result}")
    print(f"\n  总步骤：{len(plan.steps)}   失败：{len(plan.failed())}   版本：v{plan.version}")
    print("\n👉 你刚才看懂了整份计划。如果目标是'给生产库执行 DDL'，你就有机会喊停。")
    print("   这就是 P&E 在 Agent 工程里最大的价值：**把决策提前暴露，而不是让模型闷头干完**。")


if __name__ == "__main__":
    main()
