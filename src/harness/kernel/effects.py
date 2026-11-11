"""效应系统（v3 / PROPOSAL §5、§9.1）。

所有 I/O 必须先表达成 ``Effect``，由这里批量执行，走四段链
**Gate → Check → Wrap → Classify**；之后才由解释器在唯一提交点写状态。

三件事在这里定死：

* ``kind`` 可扩展：新增效应类型只需注册一个 handler，内核零改动；
* 一批效应并发执行（``asyncio.gather``），并行不需要框架算子；
* ``record_only=True`` 就是 dry_run：四段链照走，终端只记账不执行。

既有治理资产全部复用、零改动：``kernel.stage.DefaultClassify`` 负责异常
归类，``kernel.chain`` 负责层排序，``Guard/Pipe/Filter`` 可注入，
``HookEvent`` 在这里第一次接上真正的执行落点。
"""

from __future__ import annotations

import asyncio
import copy
import inspect
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Iterable, Sequence

from harness.contracts.errors import EffectError
from harness.contracts.events import HookEvent
from harness.contracts.state import State
from harness.contracts.types import Effect, Step
from harness.kernel import stage

__all__ = [
    "EffectLayer",
    "EffectRuntime",
    "EffectRunner",
    "CallbackRunner",
    "execute_effects",
    "to_step",
    "as_result_dict",
    "maybe_await",
]

#: Effect.kind → 既有 Step.kind（PROPOSAL §6 的薄适配器）
_KIND_TO_STEP = {
    "tool": "tool",
    "model": "llm",
    "child": "agent",
    "ask": "human",
    "skill": "tool",
    "wait": "human",
    "compute": "tool",
}


async def maybe_await(value: Any) -> Any:
    """层与 handler 允许同步或异步，框架统一 await。"""
    return await value if inspect.isawaitable(value) else value


def to_step(effect: Effect) -> Step:
    """``Effect → Step`` 薄适配器。

    有 ``effect.step``（旧路径）时原样返回；否则按 kind 映射，
    这样 ``kernel/stage.py`` 的四段链一行不改就能被效应喂入。
    """
    if effect.step is not None:
        return effect.step
    args = effect.args or {}
    raw_args = args.get("args", {}) or {}
    step_args = dict(raw_args) if isinstance(raw_args, dict) else {}
    return Step(
        id=effect.key or effect.kind,
        instruction=str(args.get("instruction", "")),
        tool_name=args.get("name"),
        args=step_args,
        idem_key=effect.idem_key or None,
        kind=_KIND_TO_STEP.get(effect.kind, "tool"),
    )


def as_result_dict(value: Any) -> dict[str, Any]:
    """把任意 handler 产物归一成 dict；兼容既有 ``ActionResult``。"""
    if isinstance(value, dict):
        return dict(value)
    return {
        "ok": bool(getattr(value, "ok", True)),
        "output": getattr(value, "output", ""),
        "error": getattr(value, "error", "") or "",
        "tokens": int(getattr(value, "tokens", 0) or 0),
        "raw": value,
    }


# ------------------------------------------------------------------ 横切层


def _allow(effect: Effect, state: State) -> str:
    return "allow"


def _noop_check(effect: Effect, state: State) -> None:
    return None


def _identity_wrap(effect: Effect, nxt: Callable) -> Callable:
    return nxt


def _noop_observe(effect: Effect, result: Any, state: State) -> None:
    return None


@dataclass(frozen=True)
class EffectLayer:
    """效应层的四段 + 观察。与既有 Layer/Middleware/Hook 协议一一对应。

    gate    Gate，返回 ``allow / deny / ask``；不抛异常、可短路
    check   Check，抛异常即归类为参数非法
    wrap    Wrap，``wrap(effect, nxt) -> handler(effect, state)``，洋葱包裹
    observe Hook，只读观察；异常被吞掉，不影响运行
    """

    name: str
    gate: Callable[[Effect, State], str] = _allow
    check: Callable[[Effect, State], None] = _noop_check
    wrap: Callable[[Effect, Callable], Callable] = _identity_wrap
    observe: Callable[[Effect, Any, State], None] = _noop_observe
    points: frozenset[str] = frozenset({"effect", "commit"})


# ------------------------------------------------------------------ 运行时


@dataclass
class EffectRuntime:
    """可扩展的效应运行时。

    ``handlers`` 是一张 ``kind → fn(effect, state)`` 表；新增 kind 只需
    ``extra_handlers`` 注册一个函数，不改内核、不加 ``if kind == ...``。
    """

    layers: tuple[EffectLayer, ...] = ()
    record_only: bool = False
    extra_handlers: dict[str, Callable] = field(default_factory=dict)
    guard: Any = None
    checks: tuple[Any, ...] = ()
    classify: Any = None
    hooks: tuple[Any, ...] = ()
    emit: Callable[..., Awaitable[None]] | None = None
    model: Any = None
    tool_registry: Any = None
    child_runner: Callable[..., Awaitable[Any]] | None = None

    #: 本运行消费过的效应（dry_run 用）
    effects_log: list[Effect] = field(default_factory=list)
    #: 幂等键 → 结果（PROPOSAL §12：同键同结果，避免重复副作用）
    seen: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.layers = tuple(self.layers)
        self.handlers: dict[str, Callable] = {
            "model": self._model,
            "tool": self._tool,
            "skill": self._skill,
            "ask": self._ask,
            "wait": self._wait,
            "compute": self._compute,
            "child": self._child,
        }
        self.handlers.update(self.extra_handlers or {})

    async def execute(self, effects: Sequence[Effect], state: State) -> list[Any]:
        """批量并发执行；0 个效应就是纯决策步，不落盘不记账。"""
        if not effects:
            return []
        self.effects_log.extend(effects)
        indexed = [replace(e, index=i) for i, e in enumerate(effects)]
        return list(await asyncio.gather(*(self._stages(e, state) for e in indexed)))

    # ---- 四段链 ----------------------------------------------------

    async def _stages(self, effect: Effect, state: State) -> dict[str, Any]:
        step = to_step(effect)

        async def finish(result: dict[str, Any]) -> dict[str, Any]:
            for layer in self.layers:                      # Hook：只读观察
                try:
                    await maybe_await(layer.observe(effect, result, state))
                except Exception:  # noqa: BLE001 - 观测不得影响运行
                    pass
            await self._fire_hooks(effect, result, state)
            return result

        # 幂等：同键命中直接回放，不重复产生副作用、也不重复计量
        if effect.idem_key and effect.idem_key in self.seen:
            cached = dict(self.seen[effect.idem_key])
            cached["_usage"] = {"calls": 0, "tokens": 0}
            return await finish(cached)

        # ① Gate：返回判定，不抛异常，可短路
        for layer in self.layers:
            verdict = await maybe_await(layer.gate(effect, state))
            if verdict in ("deny", "ask"):
                return await finish({
                    "ok": False,
                    "error": f"{'gate' if verdict == 'deny' else 'approval'}:{layer.name}",
                    "status": "refused" if verdict == "deny" else "needs_approval",
                })
        if self.guard is not None:
            verdict = await self.guard.check(step, state)
            if getattr(verdict, "action", "allow") in ("deny", "ask"):
                return await finish({
                    "ok": False, "error": f"policy:{getattr(verdict, 'reason', '')}",
                    "status": "refused" if verdict.action == "deny" else "needs_approval",
                })

        # ② Check：参数校验与转换
        try:
            for layer in self.layers:
                await maybe_await(layer.check(effect, state))
            for pipe in self.checks:
                step = await maybe_await(pipe.transform(step, state))
        except Exception as exc:  # noqa: BLE001 - 统一走 Classify
            return await finish(await self._failed(exc, state, phase="check"))

        # ③ Wrap：洋葱，外层在最外
        handler: Callable = self._terminal
        for layer in reversed(self.layers):
            handler = layer.wrap(effect, handler) or handler

        # ④ Classify：异常 → 失败归类的唯一映射点
        try:
            out = await maybe_await(handler(effect, state))
            result = as_result_dict(out)
        except Exception as exc:  # noqa: BLE001 - 运行边界
            result = await self._failed(exc, state, phase="wrap")

        if effect.idem_key:
            self.seen[effect.idem_key] = dict(result)
        return await finish(result)

    async def _failed(self, exc: BaseException, state: State, *, phase: str) -> dict[str, Any]:
        classifier = self.classify or stage.DefaultClassify()
        try:
            failure = await classifier.classify(exc, phase=phase, state=state)
            status = str(getattr(failure, "status", "failed"))
            reason = getattr(failure, "reason", str(exc))
        except Exception:  # noqa: BLE001 - 归类器本身坏了也不能吞掉结果
            status, reason = "failed", str(exc)
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}",
                "status": status, "reason": reason}

    async def _fire_hooks(self, effect: Effect, result: Any, state: State) -> None:
        """v3 首次给 Hook 协议接上真正落点；hook 报错只发 hook.error。"""
        point = f"effect.{effect.kind}"
        event = HookEvent(point=point, state_id=state.trace_id,
                          fields={"key": effect.key, "ok": bool(result.get("ok", True))})
        for hook in self.hooks:
            if point not in getattr(hook, "point", point):
                continue
            try:
                await maybe_await(hook(event))
            except Exception as exc:  # noqa: BLE001
                if self.emit is not None:
                    await self.emit("hook.error", error=str(exc), point=point)
        if self.emit is not None:
            await self.emit("effect", kind=effect.kind, key=effect.key,
                            ok=bool(result.get("ok", True)), rev=state.rev)

    async def _terminal(self, effect: Effect, state: State) -> dict[str, Any]:
        """终端：只记账不写业务状态（状态单一所有者由 commit 保证）。"""
        usage = {"calls": 1, "tokens": 10 if effect.kind == "model" else 0}
        if self.record_only:
            return {"ok": True, "output": f"[dry-run:{effect.kind}]", "_usage": usage}
        handler = self.handlers.get(effect.kind)
        if handler is None:
            raise EffectError(f"未注册的效应类型：{effect.kind}")
        out = await maybe_await(handler(effect, state))
        result = as_result_dict(out)
        result.setdefault("_usage", usage)
        return result

    # ---- 内置 handler ----------------------------------------------

    async def _model(self, effect: Effect, state: State) -> dict[str, Any]:
        script = state.data.get("script")
        if script is not None:
            cursor = int(state.journal.get("cursor", 0))
            reply = script[cursor] if cursor < len(script) else {"content": "done"}
            # journal 是"外部世界的既成事实"，必须即时推进；它不参与回溯。
            state.journal["cursor"] = cursor + 1
            return {"ok": True, "output": reply}
        if self.model is not None:
            messages = list(effect.args.get("messages", ()))
            reply = await maybe_await(self.model.complete(messages, None))
            return {"ok": True, "output": reply}
        raise EffectError("model 效应需要 state.data['script'] 或注入 model")

    async def _tool(self, effect: Effect, state: State) -> dict[str, Any]:
        name = effect.args.get("name")
        if not name:
            raise EffectError("tool 效应缺少 args['name']")
        tools = self.tool_registry if self.tool_registry is not None else state.data.get("tools", {})
        fn = tools[name] if isinstance(tools, dict) else tools.get(name)
        if fn is None:
            raise EffectError(f"未注册的工具：{name}")
        out = await maybe_await(fn(**(effect.args.get("args", {}) or {})))
        return {"ok": True, "output": out}

    async def _skill(self, effect: Effect, state: State) -> dict[str, Any]:
        """渐进披露三段：catalog 常驻 / body 按需 / resource 按需。"""
        catalog = state.data.get("skills", {})
        name = effect.args.get("name", "")
        part = effect.args.get("part", "body")
        if part == "catalog":
            out = {k: v.get("description", "") for k, v in catalog.items()}
        elif part == "resource":
            out = catalog[name]["resources"].get(effect.args.get("path", ""), "")
        else:
            out = catalog.get(name, {}).get("body", "")
        return {"ok": True, "output": out}

    async def _ask(self, effect: Effect, state: State) -> dict[str, Any]:
        return {"ok": True, "output": {"approved": True}}

    async def _wait(self, effect: Effect, state: State) -> dict[str, Any]:
        queue = state.data["external_queue"]     # 控制权交给外部系统
        return {"ok": True, "output": await queue.get()}

    async def _compute(self, effect: Effect, state: State) -> dict[str, Any]:
        op = effect.args.get("op")
        args = effect.args.get("args", [])
        ops = {
            "concat": lambda: "".join(map(str, args)),
            "upper": lambda: str(args[0]).upper(),
            "sum": lambda: sum(args),
            "join": lambda: " | ".join(map(str, args)),
        }
        if op not in ops:
            raise EffectError(f"未知 compute 操作：{op}")
        return {"ok": True, "output": ops[op]()}

    async def _child(self, effect: Effect, state: State) -> dict[str, Any]:
        """嵌套子运行：能力作用域由新 State 隔离，预算由父解释器统一护栏。"""
        from harness.contracts.types import Goal
        from harness.kernel.interpret import interpret

        program = effect.child or effect.args.get("program")
        if program is None:
            raise EffectError("child 效应缺少 program")
        raw_goal = effect.args.get("goal", state.goal)
        goal = Goal(raw_goal) if isinstance(raw_goal, str) else raw_goal
        child_state = State(goal=goal, session=state.session)
        child_state.data = copy.deepcopy(effect.args.get("data", {}))
        runner = self.child_runner or interpret
        out = await maybe_await(runner(program, child_state))
        status = getattr(out, "status", "completed")
        return {"ok": status in ("completed", "degraded"),
                "output": getattr(out, "answer", ""), "_child": out}


# ------------------------------------------------------------------ runner 协议


class EffectRunner:
    """``Runtime`` 只认识这个接口：``execute(effects, state) -> list[result]``。

    换掉它就能把效应喂给既有 ``stage.run_stages`` 或任何执行后端，
    内核不需要 ``if kind == ...`` 分支。
    """

    async def execute(self, effects: Sequence[Effect], state: State) -> list[Any]:  # pragma: no cover
        raise NotImplementedError


class CallbackRunner(EffectRunner):
    """把一个 ``run_one(effect, state)`` 回调包成批量 runner（旧路径兼容用）。"""

    def __init__(self, run_one: Callable[[Effect, State], Awaitable[Any]],
                 *, effects_log: list[Effect] | None = None) -> None:
        self.run_one = run_one
        self.effects_log = effects_log if effects_log is not None else []

    async def execute(self, effects: Sequence[Effect], state: State) -> list[Any]:
        if not effects:
            return []
        self.effects_log.extend(effects)
        return list(await asyncio.gather(
            *(self.run_one(replace(e, index=i), state) for i, e in enumerate(effects))
        ))


async def execute_effects(
    effects: Iterable[Effect],
    state: State,
    *,
    runtime: EffectRuntime | None = None,
    **kwargs: Any,
) -> list[Any]:
    """便捷入口：没有 runtime 就按 kwargs 造一个。"""
    rt = runtime or EffectRuntime(**kwargs)
    return await rt.execute(tuple(effects), state)
