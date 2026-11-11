"""Harness：能力容器（SPEC M15.3）。

**放在装配层而不是门面层**：它要 `new` 具体部件（Actor/Framer/Encoder），
属于"构造"职责；门面只做组合。这样 `assembly` 不必反向依赖 `fp`。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.status import RunStatus
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
    max_transitions: int = 64     # v3 全局终止护栏（HarnessConfig 注入）
    layers: tuple[Any, ...] = ()          # 装配期实例化的声明层（Layer 对象）
    auto_layers: tuple[Any, ...] = ()     # 由能力自动派生的层（护栏/检查点）
    sinks: tuple[Any, ...] = ()           # 额外事件出口（astream 用）
    token_counter: Any = None             # 精确计数器（M08：装配期注入 Framer/Encoder）
    checkpoint_store: Any = None          # 解释器级检查点存储（B06）
    reflector: Any = None                 # 最终答案判定（C05）

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
            framer=ModelFramer(system=self.system, counter=self.token_counter),
            encoder=ChatEncoder(counter=self.token_counter),
            guard=self.guard,
            pipes=tuple(self.pipes),
            filter=self.filter or DefaultClassify(),
            guardrails=tuple(self.guardrails),
            max_depth=self.max_depth,
            **backends,
        )

    async def run(self, program: Any, goal: Goal, *, sinks: tuple[Any, ...] | None = None,
                  with_auto: bool = True) -> RunResult:
        # C02：入口准入——配置了带 check_identity 的守卫就先判身份/配额；
        # deny → REFUSED（与 v1 Agent.run 同一语义）。
        if self.guard is not None and hasattr(self.guard, "check_identity"):
            verdict = await self.guard.check_identity(goal, self.namespace)
            if getattr(verdict, "action", "allow") == "deny":
                return RunResult(status=RunStatus.REFUSED,
                                 error=f"identity_denied:{getattr(verdict, 'reason', '')}")
        state = State(
            goal=goal,
            session=SessionRef(goal.session_id or "default", tenant=self.namespace.tenant),
        )
        scope = self.scope_for(goal)
        scope = replace(scope, events=_Fanout(tuple(sinks or self.sinks)))
        effective = self.with_auto_layers(program) if with_auto else program
        # v3：run_loop 已降为前端薄壳，真正的循环是 kernel.interpret.Runtime.interpret。
        return await run_loop(program=effective, state=state, scope=scope,
                              max_transitions=self.max_transitions)

    def with_auto_layers(self, program: Any) -> Any:
        """把能力派生层 + 配置声明层并进程序（B01/B04：声明层真正生效）。"""
        merged = tuple(self.auto_layers) + tuple(self.layers)
        if not merged:
            return program
        declared = tuple(getattr(program, "layers", ()) or ())
        if not hasattr(program, "layers"):
            return program
        try:
            return replace(program, layers=merged + declared)
        except (TypeError, ValueError):  # 非 dataclass 程序：层由 Runtime 承载
            return program

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
        """走完整四段，但终端只记账不执行（SPEC M1.10）。

        兼容期语义：模型照常调用以产生决策，只有工具效应被记账替代；
        底层仍是 ``interpret()``。新入口见 ``dry_run_program``。
        G02：与 ``run`` 同源——能力派生层先并进程序，不再绕过自动护栏。
        """
        state = State(goal=goal, session=SessionRef(goal.session_id or "default"))
        effects: list[Effect] = []
        await run_loop(program=self.with_auto_layers(program), state=state,
                       scope=self.scope_for(goal),
                       record_effects=effects, max_transitions=self.max_transitions)
        return effects

    # ---------------------------------------------------------------- v3 入口

    def _state_for(self, goal: Any) -> State:
        from harness.contracts.types import Goal

        g = goal if isinstance(goal, Goal) else Goal(str(goal or ""))
        return State(goal=g, session=SessionRef(g.session_id or "default",
                                                tenant=self.namespace.tenant))

    def new_runtime(self, state: State, *, sinks=None, record_only=False,
                    limits=None, layers=(), extra_handlers=None, hooks=(),
                    middleware=()) -> Any:
        """装配期注入能力：模型、护栏、事件出口、预算、横切层。

        ``Runtime`` 是唯一解释器；这里只负责把 Harness 持有的能力接上。
        ``middleware`` 是 chain 层（含 auto_layers/声明层），v3 的 model
        效应经其 model_call 插点执行（G07），不再绕过。
        """
        from harness.contracts.events import RunEvent
        from harness.kernel.interpret import Runtime, RuntimeLimits

        scope = self.scope_for(state.goal)
        if sinks is not None:
            scope = replace(scope, events=_Fanout(tuple(sinks)))

        async def emit(name, **fields):
            sink = getattr(scope, "events", None)
            if sink is None:
                return
            try:
                await sink.emit(RunEvent(name=name, trace_id=state.trace_id, fields=fields))
            except Exception:  # noqa: BLE001 - 观测不影响运行
                pass

        return Runtime(
            layers=tuple(layers),
            limits=limits or RuntimeLimits(
                max_transitions=self.max_transitions,
                max_calls=self.budget.calls,
                max_tokens=self.budget.tokens,
            ),
            record_only=record_only,
            extra_handlers=extra_handlers,
            emit=emit,
            model=self.model,
            tool_registry=self.tools,
            guard=self.guard,
            checks=tuple(self.pipes),
            classify=self.filter,
            hooks=tuple(hooks),
            checkpoint_store=self.checkpoint_store,
            budget=self.budget,
            model_call_layers=tuple(middleware),
        )

    async def interpret(self, program: Any, state: State | None = None, *, goal=None,
                        sinks=None, record_only=False, limits=None, layers=(),
                        extra_handlers=None) -> Any:
        """v3 唯一解释器入口：**任意架构**，只要满足 ``transition(state)``。

        与 ``Harness.run`` 的区别：这里不假设 ReAct 循环，程序自己决定
        顺序、分支、并行、回溯、改图和谁持有控制权。
        G01：能力派生层与声明层在此同样生效（不再只服务 ``run``）；
        G03：出口统一为 ``RunResult``（经 ``as_run_result``，Delivery 口径）。
        """
        st = state if state is not None else self._state_for(goal)
        effective = self.with_auto_layers(program)
        middleware = (tuple(self.layers) + tuple(self.auto_layers)
                      + tuple(getattr(effective, "layers", ()) or ()))
        runtime = self.new_runtime(st, sinks=sinks, record_only=record_only,
                                   limits=limits, layers=layers,
                                   extra_handlers=extra_handlers,
                                   middleware=middleware)
        out = await runtime.interpret(effective, st)
        from harness.kernel.legacy import as_run_result

        return as_run_result(out, st)

    async def dry_run_program(self, program: Any, state: State | None = None, *,
                              goal=None, **kwargs) -> tuple[Any, list[Effect]]:
        """``record_only=True``：四段链照走，终端只记账不执行；返回 (结果, 效应清单)。"""
        st = state if state is not None else self._state_for(goal)
        effective = self.with_auto_layers(program)
        middleware = (tuple(self.layers) + tuple(self.auto_layers)
                      + tuple(getattr(effective, "layers", ()) or ()))
        runtime = self.new_runtime(st, record_only=True, middleware=middleware, **kwargs)
        out = await runtime.interpret(effective, st)
        from harness.kernel.legacy import as_run_result

        return as_run_result(out, st), list(runtime.runner.effects_log)


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
