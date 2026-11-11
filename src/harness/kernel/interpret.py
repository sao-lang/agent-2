"""通用解释器（v3 / PROPOSAL §3、§5）—— 全框架唯一的循环。

    program = 初始程序
    while True:
        d = await program.transition(state)     # 架构在这里，框架不问
        if d is Halt: return Outcome
        results = await runner.execute(d.effects, state)   # 批量 → 四段链
        commit(state, d.patch, results)         # 唯一提交点
        emit(state); checkpoint(state, program)
        program = d.program or program          # 自=循环 / 历史=回溯 / 新组合=改图

框架只守不变量：状态单一所有者、能力作用域、预算、四段链、审批、
事件、检查点、**全局终止护栏**。顺序、分支、循环、并行、回溯、图、
谁持有控制权，全部是 ``program`` 的事。

内核里没有 ``if kind == ...``：新增架构、新增效应类型都不需要改这里。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

from harness.contracts.decision import (
    Decision,
    Halt,
    describe,
    static_problems,
    to_spec,
)
from harness.contracts.errors import DecisionError, NotSerializable
from harness.contracts.state import State
from harness.kernel.effects import (
    EffectLayer,
    EffectRuntime,
    EffectRunner,
    as_result_dict,
    maybe_await,
)

__all__ = ["Limits", "Outcome", "Runtime", "ValidationFailed", "interpret",
            "resume_from_checkpoint"]


class ValidationFailed(Exception):
    """装配期校验失败：能静态查的都查，不透明程序明确降级。"""


@dataclass(frozen=True)
class Limits:
    """框架新增的唯一不变量：**任何程序都必须能停下来**。

    新程序可以无限返回自己或发空效应空转，所以上限收拢到这里，
    配置由 ``HarnessConfig.max_transitions`` 等注入。
    """

    max_transitions: int = 64
    max_calls: int = 100
    max_tokens: int = 200_000
    wall_seconds: float = 30.0


@dataclass
class Outcome:
    """一次运行的产物。``state`` 与 ``extra`` 供兼容层组装 ``RunResult``。"""

    answer: str
    status: str
    transitions: int
    usage: dict[str, int]
    checkpoints: int
    trace: list[str] = field(default_factory=list)
    state: State | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Runtime:
    """解释器 = 一个循环 + 一个效应运行时。

    ``runner`` 可整体替换：默认走 v3 效应系统，旧路径注入
    ``CallbackRunner`` 把效应喂给既有 ``kernel.stage.run_stages``，
    内核自身一行不改。
    """

    def __init__(
        self,
        *,
        layers: Sequence[EffectLayer] = (),
        limits: Limits | None = None,
        record_only: bool = False,
        extra_handlers: dict[str, Callable] | None = None,
        runner: EffectRunner | None = None,
        emit: Callable[..., Awaitable[None]] | None = None,
        hooks: Sequence[Any] = (),
        model: Any = None,
        tool_registry: Any = None,
        guard: Any = None,
        checks: Sequence[Any] = (),
        classify: Any = None,
        after_commit: Callable[..., Awaitable[None]] | None = None,
        checkpoint_store: Any = None,
    ) -> None:
        # v3.1（SUPPLEMENT A2）：可插拔检查点落盘——实现 CheckpointStore 协议
        # （put(ns, sid, state, expect_rev) / get(ns, sid, rev)），复用既有
        # 存储实现（impl.stores.MemoryCheckpointStore 等）。
        self.checkpoint_store = checkpoint_store
        self.layers = tuple(layers)
        self.limits = limits or Limits()
        self.record_only = record_only
        self.emit_fn = emit
        self.after_commit = after_commit
        self.checkpoints: list[dict[str, Any]] = []
        self.events: list[str] = []
        self.runner: EffectRunner = runner or EffectRuntime(
            layers=self.layers,
            record_only=record_only,
            extra_handlers=extra_handlers,
            hooks=tuple(hooks),
            emit=self.emit,
            model=model,
            tool_registry=tool_registry,
            guard=guard,
            checks=tuple(checks),
            classify=classify,
        )
        # child 效应复用同一运行时：层、检查点、预算护栏不因嵌套而丢失。
        if isinstance(self.runner, EffectRuntime) and self.runner.child_runner is None:
            self.runner.child_runner = self.interpret

    # ---------------------------------------------------------------- 装配

    @staticmethod
    def validate(program: Any) -> list[str]:
        """能查的都查；闭包程序只保证能跑（治理分级，PROPOSAL §4.2）。"""
        problems: list[str] = []
        if not callable(getattr(program, "transition", None)):
            problems.append("程序缺少 transition()")
        else:
            problems.extend(static_problems(program))
        return problems

    # ---------------------------------------------------------------- 循环

    async def interpret(self, program: Any, state: State) -> Outcome:
        problems = self.validate(program)
        if problems:
            raise ValidationFailed("; ".join(problems))

        trace = [f"run.start:{describe(program)}"]
        await self.emit("run.start", goal=_goal_text(state), program=describe(program))
        started = time.monotonic()
        n = 0
        while True:
            halt = self._guardrail(state, n, started)
            if halt is not None:
                return await self._finish(state, halt, n, trace)

            decision = await maybe_await(program.transition(state))
            if isinstance(decision, Halt):
                return await self._finish(state, decision, n, trace)
            if not isinstance(decision, Decision):
                raise DecisionError(
                    f"transition 必须返回 Decision | Halt，收到 {type(decision)!r}"
                )

            if decision.restore is not None:
                state.restore(decision.restore)   # journal/usage 不回滚

            results = await self.runner.execute(decision.effects, state)
            kinds = ",".join(e.kind for e in decision.effects) or "pure"
            await self.emit("transition", program=getattr(program, "name", "?"),
                            kinds=kinds, note=decision.note, index=n)
            forced = self._commit(state, decision, results)
            await self.emit("commit", rev=state.rev, effects=len(decision.effects))
            if self.after_commit is not None:
                await self.after_commit(state, decision, results)

            spec: Any = "<opaque>"
            try:
                spec = to_spec(program)
            except (TypeError, NotSerializable):
                pass                              # 不透明程序明确降级
            self.checkpoints.append({
                "rev": state.rev,
                "program": spec,
                "state": state.snapshot(),
            })
            if self.checkpoint_store is not None:
                # v3.1（SUPPLEMENT A2）：落盘失败不静默——检查点是恢复的凭据，
                # 坏了必须让人知道（与观测不同：观测失败吞掉，持久化失败上抛）。
                from harness.contracts.types import Namespace

                ns = Namespace(tenant=state.session.tenant,
                               user=getattr(state.goal, "user_id", "anonymous") or "anonymous",
                               session=state.session.session_id)
                await self.checkpoint_store.put(
                    ns, state.session.session_id, state, expect_rev=state.rev - 1)
            await self.emit("checkpoint", rev=state.rev, serializable=spec != "<opaque>")
            trace.append(
                f"{n}:{getattr(program, 'name', '?')}:[{kinds}]"
                + (f":{decision.note}" if decision.note else "")
            )

            program = decision.program if decision.program is not None else program
            n += 1
            if forced is not None:
                return await self._finish(state, forced, n, trace)

    def _guardrail(self, state: State, n: int, started: float) -> Halt | None:
        """全局终止护栏：控制流可以任意，但必须能停下来。"""
        if n >= self.limits.max_transitions:
            return Halt("max_transitions", "degraded")
        if state.usage.get("calls", 0) >= self.limits.max_calls:
            return Halt("max_calls", "degraded")
        if state.usage.get("tokens", 0) >= self.limits.max_tokens:
            return Halt("max_tokens", "degraded")
        if time.monotonic() - started > self.limits.wall_seconds:
            return Halt("wall_clock", "degraded")
        return None

    # ---------------------------------------------------------------- 提交

    @staticmethod
    def _commit(state: State, decision: Decision, results: Sequence[Any]) -> Halt | None:
        """**唯一提交点**。程序只读 State，效应只返回结果；写只发生在这里。"""
        batch: dict[str, Any] = {}
        forced: Halt | None = None
        for effect, raw in zip(decision.effects, results):
            result = as_result_dict(raw)
            usage = result.pop("_usage", None) or {
                "calls": 1, "tokens": int(result.get("tokens", 0) or 0)
            }
            messages = result.pop("_messages", ())
            halt_spec = result.pop("_halt", None)
            key = effect.key or "last"
            state.results[key] = result
            batch[key] = result
            if "output" in result:
                state.data["last_output"] = result["output"]
                state.data["last_result"] = result.get("raw", result)
            state.add_usage(tokens=int(usage.get("tokens", 0)), calls=int(usage.get("calls", 0)))
            for message in messages:
                state.messages.append(message)
            if isinstance(halt_spec, dict) and forced is None:
                forced = Halt(
                    str(halt_spec.get("answer", "")),
                    str(halt_spec.get("status", "failed")),
                    dict(halt_spec.get("extra", {})),
                )
        state.results["__batch__"] = batch       # 每轮覆盖，程序只读"本批新结果"
        state.data.update(decision.patch)
        if decision.meta.get("bump_step"):
            state.step_index += 1
        state.rev += 1
        return forced

    # ---------------------------------------------------------------- 收尾

    async def _finish(self, state: State, halt: Halt, n: int,
                      trace: list[str]) -> Outcome:
        trace.append(f"run.end:{halt.status}")
        await self.emit("run.end", status=halt.status, steps=n, answer=halt.answer)
        return Outcome(
            answer=halt.answer,
            status=halt.status,
            transitions=n,
            usage=dict(state.usage),
            checkpoints=len(self.checkpoints),
            trace=trace,
            state=state,
            extra=dict(halt.extra),
        )

    async def emit(self, name: str, **fields: Any) -> None:
        """观测失败不得影响运行（SPEC M10.1）。"""
        self.events.append(name)
        if self.emit_fn is None:
            return
        try:
            await self.emit_fn(name, **fields)
        except Exception:  # noqa: BLE001
            pass


async def interpret(program: Any, state: State, **kwargs: Any) -> Outcome:
    """模块级便捷入口：``await interpret(program, state)``。"""
    return await Runtime(**kwargs).interpret(program, state)


def _goal_text(state: State) -> str:
    goal = getattr(state, "goal", "")
    return goal if isinstance(goal, str) else str(getattr(goal, "text", goal))


async def resume_from_checkpoint(store, program, session_id: str, *, ns: Any = None,
                                 rev: int | None = None, **runtime_kwargs: Any) -> Outcome:
    """从检查点续跑（SUPPLEMENT A2 / SPEC M11）。

    恢复是**重放结论不是重新推理**：状态取自检查点，已生效的副作用靠
    幂等键（Effect.idem_key）保证不重复。闭包程序不可序列化，program
    由调用方重供给（声明式程序可用 program_from_spec 重建）。
    """
    from harness.contracts.types import Namespace

    ns = ns or Namespace()
    checkpoint = await store.get(ns, session_id, rev)
    if checkpoint is None:
        raise ValidationFailed(f"没有可恢复的检查点：{session_id}" + (f"@rev{rev}" if rev else ""))
    state = checkpoint.state
    if not isinstance(state, State):
        raise ValidationFailed("检查点里的 state 形状不合法")
    return await Runtime(**runtime_kwargs).interpret(program, state)
