"""Guard：动作之前的准入层（插点 ⑤ + 接入阶段）。

默认 AllowAll 也要显式存在；不要用"没有 Guard"表示放行。
两个方法共享"不通过就拦"的语义，拆成两套组件会把同一条拒绝逻辑写两遍
（SPEC M8.1 / 基线 5.9）。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from harness.contracts.state import State
from harness.contracts.types import Goal, GuardDecision, Step


class AllowAllGuard:
    async def check_identity(self, goal: Goal, ns: Any = None) -> GuardDecision:
        return GuardDecision.allow()

    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.allow()


class DenyAllGuard:
    async def check_identity(self, goal: Goal, ns: Any = None) -> GuardDecision:
        return GuardDecision.deny("DenyAllGuard")

    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.deny("DenyAllGuard")


class FunctionGuard:
    def __init__(
        self,
        fn: Callable[[Step, State], GuardDecision | Awaitable[GuardDecision]],
        identity_fn: Callable[[Goal, Any], GuardDecision | Awaitable[GuardDecision]] | None = None,
    ) -> None:
        self.fn = fn
        self.identity_fn = identity_fn

    async def check_identity(self, goal: Goal, ns: Any = None) -> GuardDecision:
        if self.identity_fn is None:
            return GuardDecision.allow()
        decision = self.identity_fn(goal, ns)
        if hasattr(decision, "__await__"):
            decision = await decision
        return decision

    async def check(self, step: Step, state: State) -> GuardDecision:
        decision = self.fn(step, state)
        if hasattr(decision, "__await__"):
            decision = await decision
        return decision
