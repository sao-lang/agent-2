"""第 35 章产出：重规划（Replanning）的三种策略。

为什么"重规划"是独立一章？
因为它是计划系统从"能跑"到"能用"的分水岭：
  · 没有重规划 → 一个步骤失败，整个计划卡死（第 33 章的实验 A）
  · 有重规划   → 只替换失效的那部分，已完成的工作不浪费

三种策略（递进）：
  1. RETRY      —— 原样重试（最便宜，能解决瞬时故障）
  2. PATCH      —— 只替换失败步骤及其下游（真正的"重规划"）
  3. REPLAN_ALL —— 全部重来（最贵，但能处理"前提假设错了"）
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from common.planning import Executor, Plan, PlanStep, StepStatus


# ============================================================ 触发信号

@dataclass
class ReplanSignal:
    """什么情况下触发重规划。

    关键在于"分级"：不是所有失败都值得重规划。
    把 retry 就能解决的问题拿去 replan_all，是最常见的浪费。
    """

    max_retries_per_step: int = 2
    replan_budget: int = 2  # 整个计划最多重规划几次（防止无限重规划）

    def decide(self, step: PlanStep, plan: Plan, replan_count: int) -> str:
        """返回 "retry" | "patch" | "replan_all" | "give_up"。"""
        if replan_count >= self.replan_budget:
            return "give_up"

        err = (step.error or "").lower()

        # ① 瞬时故障 → 原样重试
        if any(k in err for k in ("timeout", "502", "503", "429", "connection")):
            if step.attempts < self.max_retries_per_step:
                return "retry"
            return "patch"

        # ② 参数/工具问题 → 局部替换（保留已完成的部分）
        if any(k in err for k in ("参数", "invalid", "未知动作", "not found")):
            return "patch"

        # ③ 前提假设错了 → 全部重规划
        #    怎么判断？如果失败的是"第一步"或"所有已完成的步骤都依赖它"，就说明地基错了
        if step.id == plan.steps[0].id or not step.depends_on:
            return "replan_all"

        return "patch"


# ============================================================ 三种修复动作

def retry(plan: Plan, step: PlanStep) -> Plan:
    """原样重试：把状态改回 PENDING，执行器会再跑一次。"""
    step.status = StepStatus.PENDING
    step.error = None
    return plan


def patch(plan: Plan, failed: PlanStep, new_steps: list[PlanStep]) -> Plan:
    """局部替换：只动失败步骤和依赖它的下游。

    为什么不能只替换失败步骤？
    因为下游步骤的 args 里引用的是它的 result（{sN.result}）。
    如果新步骤换了 id，下游的引用要跟着改。
    """
    new_plan = deepcopy(plan)
    new_plan.version += 1

    # 找出所有依赖链（失败步骤 + 依赖它的全部下游）
    to_replace = {failed.id}
    changed = True
    while changed:
        changed = False
        for s in new_plan.steps:
            if s.id not in to_replace and any(d in to_replace for d in s.depends_on):
                to_replace.add(s.id)
                changed = True

        # 只移除"待替换"里非完成的步骤；已完成的下游结果要保留，
        # 否则 s3/s4 被删掉后没人重算，计划就"提前完成"了（本示例第一版就踩了这个坑）
        removable = {s.id for s in new_plan.steps if s.id in to_replace and s.status != StepStatus.DONE}
        kept = [s for s in new_plan.steps if s.id not in removable]
        new_plan.steps = kept + new_steps
        return new_plan


def replan_all(plan: Plan, new_steps: list[PlanStep]) -> Plan:
    """全部重来：已完成的工作也会被丢弃。

    什么时候值得？
    当"前提假设"错了——比如原计划假设数据在 MySQL 里，实际在 Hive 里。
    这时候保留任何已完成步骤都是错的。
    """
    new_plan = Plan(goal=plan.goal, steps=new_steps, version=plan.version + 1)
    return new_plan


# ============================================================ 带重规划的执行器

@dataclass
class ReplanningExecutor(Executor):
    """在执行器上加一层"失败 → 决策 → 修复"的循环。"""

    signal: ReplanSignal = field(default_factory=ReplanSignal)
    repair_fn: Callable[[Plan, PlanStep, str], list[PlanStep]] | None = None
    replan_count: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def run(self, plan: Plan, verbose: bool = True) -> Plan:
        while True:
            plan = super().run(plan, verbose=verbose)

            failed = plan.failed()
            if not failed:
                break

            step = failed[0]
            action = self.signal.decide(step, plan, self.replan_count)
            self.history.append(
                {"version": plan.version, "failed": step.id, "error": step.error, "action": action}
            )

            if verbose:
                print(f"\n  ⚠️ [{step.id}] 失败：{step.error}")
                print(f"  → 决策：{action}")

            if action == "retry":
                plan = retry(plan, step)
            elif action in ("patch", "replan_all"):
                if self.repair_fn is None:
                    break
                self.replan_count += 1
                new_steps = self.repair_fn(plan, step, action)
                plan = patch(plan, step, new_steps) if action == "patch" else replan_all(plan, new_steps)
                if verbose:
                    print(f"  → 已修复，计划版本 v{plan.version}，共 {len(plan.steps)} 步")
            else:
                break

        return plan


# ============================================================ 让 plan.ready() 不死锁

def fix_deadlock(plan: Plan) -> Plan:
    """第 33 章实验 B 的修复：校验依赖，处理不存在的依赖与环。

    为什么需要这个？
    因为 P&E 最阴险的 bug 是"静默卡住"——不报错，只是什么都不做。
    """
    ids = {s.id for s in plan.steps}
    for s in plan.steps:
        s.depends_on = [d for d in s.depends_on if d in ids]

    # 拓扑排序检测环
    indeg = {s.id: len(s.depends_on) for s in plan.steps}
    if sum(indeg.values()) > 0:
        # 简单 Kahn：能排出序说明无环
        ready = [sid for sid, d in indeg.items() if d == 0]
        seen = 0
        while ready:
            cur = ready.pop()
            seen += 1
            for s in plan.steps:
                if cur in s.depends_on:
                    indeg[s.id] -= 1
                    if indeg[s.id] == 0:
                        ready.append(s.id)
        if seen != len(plan.steps):
            raise ValueError("计划中存在循环依赖")

    return plan
