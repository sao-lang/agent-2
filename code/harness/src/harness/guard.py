"""Guard：动作之前的准入层。

默认 AllowAll 也要显式存在；不要用“没有 Guard”表示放行。
"""

from __future__ import annotations

from typing import Awaitable, Callable

from .contracts import GuardDecision, Step
from .state import State


class AllowAllGuard:
    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.allow()


class DenyAllGuard:
    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.deny("DenyAllGuard")


class FunctionGuard:
    def __init__(self, fn: Callable[[Step, State], GuardDecision | Awaitable[GuardDecision]]) -> None:
        self.fn = fn

    async def check(self, step: Step, state: State) -> GuardDecision:
        decision = self.fn(step, state)
        if hasattr(decision, "__await__"):
            decision = await decision
        return decision
