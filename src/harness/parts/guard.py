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


class SessionGuard:
    """会话级准入（C01/C02）：quota 与 pinned_model 的**真实判定**。

    判定语义：
        - ``quota = {"max_tokens": N, "max_calls": M}``：与 ``used`` 对照，
          任一维度耗尽 → deny（拒绝而非降级，准入发生在任何动作之前）。
        - ``pinned_model``：与 ``model_name`` 不一致 → deny（会话钉选的
          模型必须精确匹配，防止静默换模型）。
    接线点：``Agent.run`` / ``Harness.run`` 入口调用 ``check_identity``；
    deny → RunStatus.REFUSED，运行根本不开始。
    """

    def __init__(
        self,
        meta: Any,
        *,
        used: dict[str, int] | None = None,
        model_name: str | None = None,
    ) -> None:
        self.meta = meta
        self.used = dict(used or {})
        self.model_name = model_name

    async def check_identity(self, goal: Goal, ns: Any = None) -> GuardDecision:
        meta = self.meta
        quota = dict(getattr(meta, "quota", None) or {})
        used = self.used
        if ns is not None:                       # ns 可携带实时用量
            used = dict(used) | dict(getattr(ns, "used", None) or {})
        for key, limit in quota.items():
            if int(used.get(key, 0)) >= int(limit):
                return GuardDecision.deny(
                    f"quota_exhausted:{key}({used.get(key, 0)}/{limit})")
        pinned = getattr(meta, "pinned_model", None)
        if pinned is not None and self.model_name is not None \
                and self.model_name != pinned:
            return GuardDecision.deny(f"model_pin_mismatch:{self.model_name}!={pinned}")
        return GuardDecision.allow()

    async def check(self, step: Step, state: State) -> GuardDecision:
        return GuardDecision.allow()


class AnswerValidator:
    """Validator 协议默认实现（C05）：最终答案的出口判定。

    最小判定集：非空、最大长度、禁止模式。生产可替换为语义判定
    （LLM-as-judge / 规则引擎），协议不变。action 语义：
    ``accept`` 放行；``retry``/``replan_all`` 在出口处降级为 DEGRADED
    并带 reason（出口没有下一轮可重试，降级是唯一诚实动作）。
    """

    def __init__(
        self,
        *,
        min_length: int = 1,
        max_length: int | None = None,
        forbidden: tuple[str, ...] = (),
    ) -> None:
        self.min_length = min_length
        self.max_length = max_length
        self.forbidden = tuple(forbidden)

    async def validate(self, answer: str, state: State) -> Any:  # -> Verdict
        from harness.contracts.types import Verdict

        text = answer or ""
        if len(text) < self.min_length:
            return Verdict(passed=False, reason="answer_empty",
                           action="retry")
        for pattern in self.forbidden:
            if pattern in text:
                return Verdict(passed=False,
                               reason=f"answer_forbidden:{pattern}",
                               action="patch")
        if self.max_length is not None and len(text) > self.max_length:
            return Verdict(passed=False, reason="answer_too_long",
                           action="patch")
        return Verdict(passed=True)
