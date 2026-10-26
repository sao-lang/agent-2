"""第 20 章 · 第 3 级：让模型生成计划，并校验它真的能跑。

运行：
    python code/ch21_plan_execute/step3_llm_plan.py

新增的两个概念：
  · **结构化输出**：让模型直接吐 JSON 对象，而不是一段待解析的文字
  · **计划校验**：在动手之前检查"依赖是否存在、有没有环、动作是否合法"

为什么校验不能省？
  一个写错的 depends_on 会让执行器**静默卡住** —— 不报错、不超时，
  只是什么都不做。这是 P&E 最阴险的 bug。

这一级不调用真实模型：用一个"会犯错的规划器"模拟模型输出，
因为教学要的不是"模型有多聪明"，而是"你怎么接住它的错"。
接真实模型只需要把 `FakePlanner()` 换成 `llm.with_structured_output(...)`。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

VALID_ACTIONS = {"search", "compare", "answer"}


# ---------------------------------------------------------------- 规划器

@dataclass
class FakePlanner:
    """按剧本吐计划。剧本里**故意放了三处错**，用来演示校验。"""

    script: str
    turn: int = 0

    def invoke(self, goal: str) -> str:
        self.turn += 1
        return self.script


BAD_PLAN = json.dumps({
    "steps": [
        {"goal": "查竞品A", "action": "search", "args": {"q": "竞品A"}, "depends_on": []},
        {"goal": "查竞品B", "action": "search", "args": {"q": "竞品B"}, "depends_on": []},
        {"goal": "查竞品C", "action": "search_web", "args": {"q": "竞品C"}, "depends_on": []},
        {"goal": "横向对比", "action": "compare",
         "args": {"a": "{s1.result}", "b": "{s2.result}"}, "depends_on": [1, 2, 9]},
        {"goal": "给出建议", "action": "answer", "args": {"summary": "{s4.result}"},
         "depends_on": [4, 5]},
    ]
}, ensure_ascii=False)


# ---------------------------------------------------------------- 计划

@dataclass
class Step:
    id: str
    goal: str
    action: str
    args: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    plan: list[Step] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse(raw: str) -> ParseResult:
    """把模型吐的 JSON 变成 Step 列表。解析失败也要说清哪一条错了。"""
    out = ParseResult()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        out.errors.append(f"JSON 解析失败：{e}")
        return out

    for i, item in enumerate(data.get("steps", []), 1):
        action = item.get("action", "")
        bad = [k for k in ("goal", "action") if not item.get(k)]
        if bad:
            out.errors.append(f"第 {i} 步缺字段：{bad}")
        if action and action not in VALID_ACTIONS:
            out.errors.append(f"第 {i} 步的 action「{action}」不合法，只能是 {sorted(VALID_ACTIONS)}")
        out.plan.append(Step(
            id=f"s{i}",
            goal=item.get("goal", ""),
            action=action,
            args=item.get("args", {}),
            depends_on=[f"s{d}" for d in item.get("depends_on", [])],
        ))
    return out


def validate(steps: list[Step]) -> list[str]:
    """动手之前必须过这三关。"""
    errors: list[str] = []
    ids = {s.id for s in steps}

    for s in steps:
        for d in s.depends_on:
            if d not in ids:
                errors.append(f"{s.id} 依赖了不存在的 {d}（会让执行器静默卡住）")

    # 环检测：DFS 三色标记
    state: dict[str, int] = {}

    def has_cycle(sid: str) -> bool:
        if state.get(sid) == 1:
            return True
        if state.get(sid) == 2:
            return False
        state[sid] = 1
        node = next((x for x in steps if x.id == sid), None)
        for d in (node.depends_on if node else []):
            if d in ids and has_cycle(d):
                return True
        state[sid] = 2
        return False

    for s in steps:
        if s.id in ids and has_cycle(s.id):
            errors.append(f"{s.id} 参与的依赖链里存在环")
            break

    if steps and steps[-1].action != "answer":
        errors.append("最后一步不是 answer —— 计划可能产出不了结论")
    return errors


def main() -> None:
    print("=" * 74)
    print("第 3 级：让模型生成计划 + 动手前校验")
    print("=" * 74)

    raw = FakePlanner(BAD_PLAN).invoke("对比三家竞品定价")
    print("\n【模型原始输出（节选）】")
    print("  " + raw[:160].replace("\n", "\n  ") + " ...")

    parsed = parse(raw)
    print(f"\n【解析】得到 {len(parsed.plan)} 步，解析错误 {len(parsed.errors)} 个")
    for e in parsed.errors:
        print(f"  ✘ {e}")

    print("\n【校验】")
    errs = validate(parsed.plan)
    for e in errs:
        print(f"  ✘ {e}")

    print("\n" + "=" * 74)
    print("如果跳过校验会发生什么")
    print("=" * 74)
    print("  · action「search_web」不存在 → 执行到第 3 步时抛 KeyError")
    print("  · depends_on 里有 9（不存在）→ 第 4 步永远等不到前置，**静默卡住**")
    print("  · 第 5 步依赖自己（4, 5）→ 成环，永远不 ready")
    print()
    print("  ⚠️ 最危险的是第二条和第三条：**它们不报错、不超时，什么都不做。**")
    print("     线上表现是「任务一直转圈」，你以为是模型慢，其实是计划写错了。")
    print()
    print("  👉 所以：规划完之后，先 validate()，再 execute()。")
    print("     校验失败就让模型重规划（带着错误信息回去），而不是硬跑。")

    print("\n" + "=" * 74)
    print("接真实模型的样子（只改一行）")
    print("=" * 74)
    print("  from pydantic import BaseModel")
    print("  class PlannedStep(BaseModel):")
    print("      goal: str; action: Literal['search','compare','answer']")
    print("      args: dict; depends_on: list[int]")
    print("  structured = llm.with_structured_output(PlannedStep)")
    print("  # action 用 Literal 约束后，「search_web」这类值在 schema 层就被拒了")


if __name__ == "__main__":
    main()
