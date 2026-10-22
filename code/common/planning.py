"""第 33 章产出：Plan-and-Execute 的核心数据结构与执行器。

和 ReAct 的本质区别：
  ReAct   ：走一步看一步，路径是涌现出来的
  P&E     ：先产出完整计划，再逐步执行，路径是先声明后验证的

本节先不接模型，用确定性的"假规划器"，把数据流跑通。
第 33 章后半段（接真实模型）会在这个骨架上替换两个函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """一个可执行的步骤。

    为什么要有 id 和 depends_on？
    因为"重规划"需要**只替换失效的那部分**，而不是全部重来。
    没有依赖关系，你只能推倒重来（第 35 章会用到）。
    """

    id: str
    goal: str  # 这一步要达成什么（面向人，用于可读性）
    action: str  # 调用什么（工具名 / "answer" / "research"）
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str | None = None
    attempts: int = 0


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    version: int = 1

    def by_id(self, sid: str) -> PlanStep | None:
        return next((s for s in self.steps if s.id == sid), None)

    def ready(self) -> list[PlanStep]:
        """依赖都完成了、自己还没跑的步骤。"""
        done = {s.id for s in self.steps if s.status == StepStatus.DONE}
        return [
            s
            for s in self.steps
            if s.status == StepStatus.PENDING and all(d in done for d in s.depends_on)
        ]

    def is_complete(self) -> bool:
        return all(s.status in (StepStatus.DONE, StepStatus.SKIPPED) for s in self.steps)

    def failed(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]


def make_plan(goal: str, specs: list[tuple[str, str, dict[str, Any], list[str]]]) -> Plan:
    """从 (goal, action, args, depends_on) 快速构造计划。"""
    steps = [
        PlanStep(id=f"s{i + 1}", goal=g, action=a, args=args, depends_on=deps)
        for i, (g, a, args, deps) in enumerate(specs)
    ]
    return Plan(goal=goal, steps=steps)


@dataclass
class Executor:
    """执行计划：按依赖顺序跑，记录每一步的结果与错误。

    关键设计：
      · 执行前先检查依赖（不满足就跳过，不浪费时间）
      · 单步失败不中断整体（标记 FAILED，交给第 35 章的重规划）
      · 每步结果写进 plan，后续步骤可以引用（通过 {s1.result} 占位）
    """

    tools: dict[str, Callable[[dict[str, Any]], str]]
    max_attempts: int = 2

    def run(self, plan: Plan, verbose: bool = True) -> Plan:
        while not plan.is_complete() and plan.ready():
            for step in plan.ready():
                step.status = StepStatus.RUNNING
                step.attempts += 1
                resolved_args = _resolve(step.args, plan)

                fn = self.tools.get(step.action)
                if fn is None:
                    step.status = StepStatus.FAILED
                    step.error = f"未知动作：{step.action}"
                else:
                    try:
                        step.result = str(fn(resolved_args))
                        step.status = StepStatus.DONE
                    except Exception as e:  # noqa: BLE001
                        step.status = StepStatus.FAILED
                        step.error = f"{type(e).__name__}: {e}"

                if verbose:
                    mark = "✔" if step.status == StepStatus.DONE else "✘"
                    print(f"  {mark} [{step.id}] {step.goal} → {step.result or step.error}")
        return plan


def _resolve(args: dict[str, Any], plan: Plan) -> dict[str, Any]:
    """把 {"q": "{s1.result}"} 解析成上一步的实际结果。

    这是 P&E 最关键的能力：**后面的步骤能用到前面的结果**，
    而不是像 ReAct 那样靠历史消息隐式传递。
    """
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("{") and v.endswith(".result}"):
            sid = v[1:-8]
            prev = plan.by_id(sid)
            out[k] = prev.result if prev else ""
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- 假工具

def tool_search(args: dict) -> str:
    q = args.get("q", "")
    db = {
        "竞品A": "竞品A：¥99/月，按席位计费，含基础模型。",
        "竞品B": "竞品B：¥129/月，按调用量计费，含高级模型。",
        "竞品C": "竞品C：¥79/月，免费额度 10 万 token。",
    }
    return db.get(q, f"未找到 {q}")


def tool_compare(args: dict) -> str:
    return f"对比结论：{args.get('a', '')[:20]}... vs {args.get('b', '')[:20]}... 价差约 30%"


def tool_answer(args: dict) -> str:
    return f"最终建议：{args.get('summary', '')}"


TOOLS = {"search": tool_search, "compare": tool_compare, "answer": tool_answer}


def demo_plan() -> Plan:
    return make_plan(
        goal="对比三家竞品定价并给出建议",
        specs=[
            ("查竞品A定价", "search", {"q": "竞品A"}, []),
            ("查竞品B定价", "search", {"q": "竞品B"}, []),
            ("查竞品C定价", "search", {"q": "竞品C"}, []),
            ("对比A与B", "compare", {"a": "{s1.result}", "b": "{s2.result}"}, ["s1", "s2"]),
            ("给出建议", "answer", {"summary": "{s4.result}"}, ["s4"]),
        ],
    )
