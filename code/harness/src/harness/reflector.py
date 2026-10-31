"""Reflector：校验层。没有外部证据时，用 NullReflector 显式表示“不校验”。"""

from __future__ import annotations

from typing import Awaitable, Callable

from .contracts import ActionResult, Verdict
from .state import State


class NullReflector:
    async def review(self, result: ActionResult, state: State) -> Verdict:
        return Verdict(passed=True, action="accept", reason="no reflector")


class FunctionReflector:
    def __init__(self, fn: Callable[[ActionResult, State], Verdict | Awaitable[Verdict]]) -> None:
        self.fn = fn

    async def review(self, result: ActionResult, state: State) -> Verdict:
        verdict = self.fn(result, state)
        if hasattr(verdict, "__await__"):
            verdict = await verdict
        return verdict
