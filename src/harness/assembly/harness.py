"""Harness：能力容器（SPEC M15.3）。

**放在装配层而不是门面层**：它要 `new` 具体部件（Actor/Framer/Encoder），
属于"构造"职责；门面只做组合。这样 `assembly` 不必反向依赖 `fp`。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable

from harness.contracts.decision import Decision
from harness.contracts.errors import ApprovalExpired, HarnessError
from harness.contracts.events import RunEvent
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.status import RunStatus
from harness.contracts.types import (
    ActionResult,
    ApprovalRequest,
    Budget,
    Effect,
    Goal,
    ModelRequest,
    ModelResponse,
    SessionRef,
    Step,
    StepRequest,
    StepResponse,
)
from harness.kernel import chain, stage
from harness.kernel.effects import CallbackRunner
from harness.kernel.interpret import Outcome, Runtime, RuntimeLimits
from harness.kernel.scope import Namespace, RunScope
from harness.parts.actor import LlmActor
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
    max_transitions: int = 64     # 全局终止护栏（HarnessConfig 注入）
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
        # deny → REFUSED。
        if self.guard is not None and hasattr(self.guard, "check_identity"):
            verdict = await self.guard.check_identity(goal, self.namespace)
            if getattr(verdict, "action", "allow") == "deny":
                return RunResult(status=RunStatus.REFUSED,
                                 error=f"identity_denied:{getattr(verdict, 'reason', '')}")
        state = State(
            goal=goal,
            session=SessionRef(goal.session_id or "default", tenant=self.namespace.tenant),
        )
        return await self._run_state(program, state, sinks=sinks, with_auto=with_auto)

    async def _run_state(self, program: Any, state: State, *,
                         sinks: tuple[Any, ...] | None = None,
                         with_auto: bool = True) -> RunResult:
        """以给定 State 进入唯一循环（``run`` 与 ``resume`` 共用的入口）。"""
        scope = self.scope_for(state.goal)
        scope = replace(scope, events=_Fanout(tuple(sinks or self.sinks)))
        effective = self.with_auto_layers(program) if with_auto else program
        # 唯一循环是 kernel.interpret.Runtime.interpret；body.next_step 经
        # Program.transition 翻译为 transition 协议，四段链由 CallbackRunner 转接。
        return await self._run_body(effective, state, scope,
                                      max_transitions=self.max_transitions)

    async def resume(self, program: Any, session_id: str, decision: Any = None, *,
                     rev: int | None = None, ns: Any = None,
                     sinks: tuple[Any, ...] | None = None) -> RunResult:
        """恢复运行（SUPPLEMENT A2）：审批续跑或崩溃恢复——**重放结论不是重新推理**。

        ``decision=None`` → 崩溃恢复：从 ``checkpoint_store`` 最近（或指定 ``rev``）
        检查点重放续跑；已生效副作用靠幂等键保证不重复。
        ``decision=审批结果`` → 读取挂起的审批项，approve / reject / modify
        处理后重入唯一循环；批准的步骤跳过 Gate（人工已批准，不再二次询问）。
        program 由调用方重供给（闭包程序不可序列化，程序是可重建的值）。
        """
        if self.checkpoint_store is None:
            raise HarnessError("Harness 未配置 checkpoint_store，无法恢复运行")
        from harness.contracts.types import Namespace

        ns = ns or Namespace(tenant=self.namespace.tenant, session=session_id)
        checkpoint = await self.checkpoint_store.get(ns, session_id, rev)
        if checkpoint is None:
            raise HarnessError(f"没有可恢复的检查点：{session_id}"
                               + (f"@rev{rev}" if rev is not None else ""))
        state = checkpoint.state
        if not isinstance(state, State):
            raise HarnessError("检查点里的 state 形状不合法")

        if decision is not None:
            pending_raw = state.data.get("pending")
            if not pending_raw:
                raise HarnessError(f"session {session_id} 没有待审批项")
            pending = ApprovalRequest(
                id=pending_raw["id"], step=Step(**pending_raw["step"]),
                reason=pending_raw.get("reason", ""), card=pending_raw.get("card", {}),
                expires_at=pending_raw.get("expires_at", ""),
                session_id=pending_raw.get("session_id", ""),
            )
            if pending.expires_at and pending.expires_at < _now_iso():
                state.data.pop("pending", None)
                await self.checkpoint_store.put(ns, session_id, state)
                raise ApprovalExpired(f"审批已过期：{pending.id}")
            if decision.action == "reject":
                state.data.pop("pending", None)
                state.status = RunStatus.REFUSED
                return RunResult(status=RunStatus.REFUSED, state=state,
                                 error=decision.reason or "rejected",
                                 trace_id=state.trace_id, rev=state.rev)
            if decision.action == "modify":
                pending = replace(pending, step=replace(
                    pending.step, args={**pending.step.args, **decision.args}))
            state.data.pop("pending", None)
            state.data["_approved_step"] = asdict(pending.step)
            state.data["_approved_by"] = decision.by
        return await self._run_state(program, state, sinks=sinks)

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

        与 ``run`` 同源——能力派生层先并进程序，不再绕过自动护栏；
        record_effects 非空时终端只记账，由 ``_run_body`` 直连解释器。
        """
        state = State(goal=goal, session=SessionRef(goal.session_id or "default"))
        effects: list[Effect] = []
        await self._run_body(self.with_auto_layers(program), state,
                               self.scope_for(goal),
                               record_effects=effects,
                               max_transitions=self.max_transitions)
        return effects

    async def _run_body(self, program: Any, state: State, scope: Any, *,
                          record_effects: list | None = None,
                          max_transitions: int | None = None) -> RunResult:
        """body 型程序（``body.next_step``）的执行路径；``run_stages`` 四段链保留。

        ``body.next_step`` 经 ``Program.transition`` 翻译成 ``Decision | Halt``，
        效应由 ``CallbackRunner`` 转接给既有 ``stage.run_stages``，
        循环只在 ``kernel.interpret.Runtime.interpret`` 里。
        """
        augmented = replace(
            scope,
            layers=tuple(program.layers),
            model_call=_make_model_call(program, scope),
        )
        program = replace(program, scope=augmented)
        tool_layers = chain.resolve(program.layers, "tool_call")
        step_layers = chain.resolve(program.layers, "step")

        async def terminal(step, st):
            if record_effects is not None:
                record_effects.append(Effect(kind="tool", step=step))
                return ActionResult(step_id=step.id, ok=True, output="[dry-run]")
            return await augmented.actor.step(step, st, augmented)

        async def run_one(effect, st):
            step = effect.step
            # Gate 直判：ask 需要审批卡片副作用，无法塞进
            # 链；deny/allow 在这里判完后不再重复过 run_stages 的 Gate 段。
            # resume 批准的步骤带 skip_guard，跳过 Gate（人工已批准）。
            skip_guard = bool(effect.args.get("skip_guard", False))
            # resume 批准的步骤完全跳过 Gate；其余步骤在这里直判一次
            # （ask 需要审批卡片副作用，无法塞进链），判完后不再重复过
            # run_stages 的 Gate 段。
            gate = None if skip_guard else augmented.guard
            if gate is not None:
                verdict = await gate.check(step, st)
                action = getattr(verdict, "action", "allow")
                if action == "deny":
                    return _halt_dict("refused", reason=verdict.reason)
                if action == "ask":
                    pending = ApprovalRequest(
                        id=uuid.uuid4().hex[:12],
                        step=step,
                        reason=verdict.reason,
                        card=verdict.card,
                        expires_at=_expires_at(verdict.expires_in),
                        session_id=st.session.session_id,
                    )
                    st.data["pending"] = asdict(pending)
                    return {"ok": False,
                            "_halt": {"status": "needs_approval", "answer": "",
                                      "extra": {"pending": pending}},
                            "_usage": {"calls": 0, "tokens": 0},
                            "skip_tail": True}
                gate = None   # allow 已判
            await _emit(augmented, st, "step.start", step=step.id, tool=step.tool_name or "")
            sr = await stage.run_stages(
                step, st, terminal=terminal, gate=gate,
                checks=tuple(augmented.pipes), layers=tool_layers, classify=augmented.filter,
            )
            if sr.failure is not None:
                return {
                    "ok": False,
                    "_halt": {"status": str(sr.failure.status), "answer": "",
                              "extra": {"reason": sr.failure.reason}},
                    "_usage": {"calls": 0, "tokens": 0},
                }
            ar = sr.result
            return {
                "ok": bool(getattr(ar, "ok", False)),
                "output": getattr(ar, "output", "") if ar is not None else "",
                "raw": ar,
                # LlmActor.propose() 已经记过模型调用，这里不能重复计量。
                "_usage": {"calls": 0, "tokens": 0},
            }

        async def after_commit(st, decision, results):
            info = results[0] if results and isinstance(results[0], dict) else None
            if info is not None and info.get("skip_tail"):
                return   # 挂起审批等终止分支：不发 step.end、不执行 step 层
            step = decision.effects[0].step if decision.effects else None
            ok = bool(info.get("ok", False)) if info is not None else False
            if step is not None:
                await _emit(augmented, st, "step.end", step=step.id, ok=ok)
            if step_layers:
                await chain.execute(step_layers, StepRequest(state=st, step=step), _identity)

        await _emit(augmented, state, "run.start", goal=state.goal.text)
        ceiling = min(max_transitions or program.max_steps + 2, program.max_steps + 2)
        # Budget 已映射进解释器 Limits——预算耗尽由护栏触发 degraded，这里不再自查。
        budget = getattr(augmented, "budget", None)
        runtime = Runtime(
            limits=RuntimeLimits(max_transitions=ceiling,
                          max_calls=budget.calls if budget is not None else 10 ** 9,
                          max_tokens=budget.tokens if budget is not None else 10 ** 9,
                          wall_seconds=300.0),
            runner=CallbackRunner(run_one),
            after_commit=after_commit,
            budget=budget,   # 单点记账：_commit 同时写 State.usage 与 Budget
            emit=None,       # 兼容期：新增事件记在 runtime.events，不改变旧 sink 的事件序列
            checkpoint_store=self.checkpoint_store,   # A2：每 commit 落盘，供 resume 重放
        )
        out = await runtime.interpret(program, state)
        result = as_run_result(out, state)
        # C07：补 run 插点——声明在 run 上的层（尤其 output_guard_layer 的出口扫描）
        # 对最终 RunResult 生效；拦截/改写直接落在出口上。
        run_layers = chain.resolve(program.layers, "run")
        if run_layers:
            async def _passthrough(req):
                return req

            result = await chain.execute(run_layers, result, _passthrough)
            state.status = result.status
        await _emit(augmented, state, "run.end", status=str(result.status),
                    steps=state.step_index)
        return result

    # ---------------------------------------------------------------- 解释器入口

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
        ``middleware`` 是 chain 层（含 auto_layers/声明层），model
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
        """唯一解释器入口：**任意架构**，只要满足 ``transition(state)``。

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


def as_run_result(out: Outcome, state: State) -> RunResult:
    """新内核的 Outcome → 既有 ``RunResult``（七态枚举）。"""
    try:
        status = RunStatus(out.status)
    except ValueError:
        status = RunStatus.FAILED
    state.status = status
    reason = str(out.extra.get("reason", ""))
    return RunResult(
        status=status,
        answer=out.answer,
        state=state,
        usage=dict(state.usage),
        pending=out.extra.get("pending"),
        error=(reason or None) if status is not RunStatus.COMPLETED else None,
        trace_id=state.trace_id,
        rev=state.rev,
    )


def _halt_dict(status: str, answer: str = "", **extra: Any) -> dict[str, Any]:
    """Gate/失败分支：让解释器在唯一提交点之后终止，不产生副作用计量。"""
    return {
        "ok": False,
        "_halt": {"status": status, "answer": answer, "extra": extra},
        "_usage": {"calls": 0, "tokens": 0},
        "skip_tail": True,
    }


def _expires_at(seconds: int | None) -> str:
    if not seconds:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _make_model_call(program: Any, scope: Any):
    """把 model_call 点上的层封成可调用对象交给 Actor（SPEC M2.2）。"""
    layers = chain.resolve(program.layers, "model_call")

    async def call(request: ModelRequest) -> ModelResponse:
        async def terminal(req: ModelRequest) -> ModelResponse:
            reply = await scope.model.complete(list(req.messages), list(req.tools) or None)
            # M05：回包用量带上，显式挂载的 budget_layer 才能真正扣减。
            return ModelResponse(reply=reply, usage=dict(getattr(reply, "usage", {}) or {}))

        if layers:
            return await chain.execute(layers, request, terminal)
        return await terminal(request)

    return call


async def _emit(scope: Any, state: State, name: str, **fields: Any) -> None:
    """事件是唯一对外观察面；观测失败不得影响运行（SPEC M10.1）。"""
    sink = getattr(scope, "events", None)
    if sink is None:
        return
    try:
        await sink.emit(RunEvent(name=name, trace_id=state.trace_id, fields=fields))
    except Exception:  # noqa: BLE001
        pass


async def _identity(req):
    return StepResponse(step=getattr(req, "step", None))


__all__ = ["Harness"]
