"""Harness：能力容器（SPEC M15.3）。

**放在装配层而不是门面层**：它要 `new` 具体部件（Actor/Framer/Encoder），
属于"构造"职责；门面只做组合。这样 `assembly` 不必反向依赖 `fp`。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.types import Budget, Effect, Goal, SessionRef
from harness.kernel.loop import run_loop
from harness.kernel.scope import Namespace, RunScope
from harness.parts.actor_v2 import LlmActor
from harness.parts.framing import ChatEncoder, ModelFramer
from harness.parts.tools import ToolRegistry


@dataclass
class Harness:
    """模型、工具、存储、后端。**不持有任何策略。**"""

    model: Any = None
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    budget: Budget = field(default_factory=Budget)
    namespace: Namespace = field(default_factory=Namespace)
    stores: dict[str, Any] = field(default_factory=dict)
    backends: dict[str, Any] = field(default_factory=dict)
    guard: Any = None
    pipes: tuple[Any, ...] = ()
    filter: Any = None
    guardrails: tuple[Any, ...] = ()
    system: str = ""
    max_depth: int = 2
    layers: tuple[Any, ...] = ()          # 装配期声明的层（LayerSpec），供 to_spec 使用

    @classmethod
    def of(cls, model: Any = None, *, tools: Iterable[Any] = (), **kwargs: Any) -> "Harness":
        registry = ToolRegistry()
        if tools:
            registry.add(*tools)
        return cls(model=model, tools=registry, **kwargs)

    def scope_for(self, goal: Goal) -> RunScope:
        from harness.kernel.stage import DefaultClassify

        known = set(RunScope.__dataclass_fields__)
        backends = {k: v for k, v in self.backends.items() if k in known}
        return RunScope(
            namespace=replace(self.namespace, session=goal.session_id or "default"),
            budget=self.budget,
            actor=LlmActor(model=self.model, tools=self.tools),
            framer=ModelFramer(system=self.system),
            encoder=ChatEncoder(),
            guard=self.guard,
            pipes=tuple(self.pipes),
            filter=self.filter or DefaultClassify(),
            guardrails=tuple(self.guardrails),
            max_depth=self.max_depth,
            **backends,
        )

    async def run(self, program: Any, goal: Goal) -> RunResult:
        state = State(
            goal=goal,
            session=SessionRef(goal.session_id or "default", tenant=self.namespace.tenant),
        )
        return await run_loop(program=program, state=state, scope=self.scope_for(goal))

    async def dry_run(self, program: Any, goal: Goal) -> list[Effect]:
        """走完整四段，但终端只记账不执行（SPEC M1.10）。"""
        state = State(goal=goal, session=SessionRef(goal.session_id or "default"))
        effects: list[Effect] = []
        await run_loop(program=program, state=state, scope=self.scope_for(goal),
                       record_effects=effects)
        return effects


__all__ = ["Harness"]
