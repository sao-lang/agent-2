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
    auto_layers: tuple[Any, ...] = ()     # 由能力自动派生的层（护栏/检查点）
    sinks: tuple[Any, ...] = ()           # 额外事件出口（astream 用）

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
            model=self.model,
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

    async def run(self, program: Any, goal: Goal, *, sinks: tuple[Any, ...] | None = None,
                  with_auto: bool = True) -> RunResult:
        state = State(
            goal=goal,
            session=SessionRef(goal.session_id or "default", tenant=self.namespace.tenant),
        )
        scope = self.scope_for(goal)
        scope = replace(scope, events=_Fanout(tuple(sinks or self.sinks)))
        effective = self.with_auto_layers(program) if with_auto else program
        return await run_loop(program=effective, state=state, scope=scope)

    def with_auto_layers(self, program: Any) -> Any:
        """把能力派生出的层并进程序（护栏、检查点等）。"""
        if not self.auto_layers:
            return program
        return replace(program, layers=tuple(self.auto_layers) + tuple(program.layers))

    async def astream(self, program: Any, goal: Goal):
        """流式出口：**共用同一条内核**，只是多挂一个队列 sink（SPEC M11.2）。"""
        import asyncio

        from harness.contracts.events import RunEvent

        queue: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=256)
        sink = _QueueSink(queue)
        task = asyncio.create_task(self.run(program, goal, sinks=(sink,)))
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {getter, task}, return_when=asyncio.FIRST_COMPLETED
                )
                if getter in done:
                    event = getter.result()
                    yield event
                    if event.name == "run.end":
                        break
                    continue
                getter.cancel()
                while not queue.empty():
                    yield queue.get_nowait()
                break
        finally:
            await task

    async def dry_run(self, program: Any, goal: Goal) -> list[Effect]:
        """走完整四段，但终端只记账不执行（SPEC M1.10）。"""
        state = State(goal=goal, session=SessionRef(goal.session_id or "default"))
        effects: list[Effect] = []
        await run_loop(program=program, state=state, scope=self.scope_for(goal),
                       record_effects=effects)
        return effects


class _Fanout:
    """把事件扇出到多个 sink；任一失败不影响其余。"""

    def __init__(self, sinks: tuple[Any, ...]) -> None:
        self.sinks = tuple(s for s in sinks if s is not None)

    async def emit(self, event: Any) -> None:
        for sink in self.sinks:
            try:
                await sink.emit(event)
            except Exception:  # noqa: BLE001 - 观测不影响运行
                pass


class _QueueSink:
    """把事件推入 asyncio 队列，供 astream 消费。溢出丢最旧并计数。"""

    def __init__(self, queue: Any) -> None:
        self.queue = queue
        self.dropped = 0

    async def emit(self, event: Any) -> None:
        import asyncio

        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(event)
            except Exception:  # noqa: BLE001
                pass
            self.dropped += 1


__all__ = ["Harness"]
