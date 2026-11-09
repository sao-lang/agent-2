"""通用解释器方案 · 唯一解释器（提案样张）。

对应方案第 5 节。内核只做四件事：
    transition → 批量执行效应（四段链）→ 提交状态 → 换下一个程序
内核不认识任何架构形状：没有 step / body / seq / branch / loop / graph。

四段链语义与现有 harness 的 kernel/stage.py 一致：
    Gate 返回判定不抛异常 · Check 校验参数 · Wrap 包裹执行 · Classify 异常映射
"""

from __future__ import annotations

import asyncio
import copy
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from proposals.contracts import (
    Decision, Effect, Halt, Layer, State, describe, to_spec, capabilities,
)


class GateDenied(Exception):
    pass


class ValidationFailed(Exception):
    pass


@dataclass
class Limits:
    """框架新增的唯一不变量：任何程序都必须能停下来。"""

    max_transitions: int = 64
    max_calls: int = 100
    max_tokens: int = 200_000


@dataclass
class Outcome:
    answer: str
    status: str
    transitions: int
    usage: dict[str, int]
    checkpoints: int
    trace: list[str] = field(default_factory=list)


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Runtime:
    """效应运行时。handlers 可扩展：新增 kind 只需注册一个函数。"""

    def __init__(
        self,
        *,
        layers: tuple[Layer, ...] = (),
        limits: Limits | None = None,
        record_only: bool = False,
        extra_handlers: dict[str, Callable] | None = None,
    ) -> None:
        self.layers = tuple(layers)
        self.limits = limits or Limits()
        self.record_only = record_only
        self.checkpoints: list[dict[str, Any]] = []
        self.handlers: dict[str, Callable] = {
            "model": self._model,
            "tool": self._tool,
            "skill": self._skill,
            "ask": self._ask,
            "wait": self._wait,
            "compute": self._compute,
            "child": self._child,
        }
        self.handlers.update(extra_handlers or {})

    # ------------------------------------------------------------ 装配期校验
    @staticmethod
    def validate(program: Any) -> list[str]:
        """能查的都查，查不了的明确降级（治理分级）。"""

        problems: list[str] = []
        if not hasattr(program, "transition"):
            problems.append("程序缺少 transition()")
        check = getattr(program, "static_check", None)
        if callable(check):
            problems.extend(check())
        return problems

    # ------------------------------------------------------------ 解释器
    async def interpret(self, program: Any, state: State) -> Outcome:
        problems = self.validate(program)
        if problems:
            raise ValidationFailed("; ".join(problems))

        trace: list[str] = [f"run.start:{describe(program)}"]
        n = 0
        while True:
            if n >= self.limits.max_transitions:
                return self._finish(state, Halt("max_transitions", "degraded"), n, trace)
            if state.usage["calls"] >= self.limits.max_calls:
                return self._finish(state, Halt("max_calls", "degraded"), n, trace)

            decision = program.transition(state)
            if isinstance(decision, Halt):
                return self._finish(state, decision, n, trace)
            if not isinstance(decision, Decision):
                raise TypeError(f"transition 必须返回 Decision | Halt，收到 {type(decision)!r}")

            if decision.restore is not None:
                state.restore(decision.restore)

            results = await asyncio.gather(
                *(self._stages(effect, state) for effect in decision.effects)
            )
            self._commit(state, decision, results)

            spec: Any = "<opaque>"
            try:
                spec = to_spec(program)
            except TypeError:
                pass
            self.checkpoints.append({"rev": state.rev, "program": spec})

            trace.append(
                f"{n}:{program.name}:[{','.join(e.kind for e in decision.effects) or 'pure'}]"
                + (f":{decision.note}" if decision.note else "")
            )
            if decision.program is not None:
                program = decision.program
            n += 1

    def _finish(self, state: State, halt: Halt, n: int, trace: list[str]) -> Outcome:
        trace.append(f"run.end:{halt.status}")
        return Outcome(
            answer=halt.answer,
            status=halt.status,
            transitions=n,
            usage=dict(state.usage),
            checkpoints=len(self.checkpoints),
            trace=trace,
        )

    # ------------------------------------------------------------ 四段链
    async def _stages(self, effect: Effect, state: State) -> Any:
        terminal: Callable = self._terminal

        # ① Gate
        for layer in self.layers:
            verdict = layer.gate(effect, state)
            if verdict == "deny":
                return {"ok": False, "error": f"gate:{layer.name}"}
            if verdict == "ask":
                return {"ok": False, "error": f"approval:{layer.name}"}

        # ② Check
        try:
            for layer in self.layers:
                layer.check(effect, state)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"invalid:{exc}"}

        # ③ Wrap
        handler = terminal
        for layer in reversed(self.layers):
            handler = layer.wrap(effect, handler)

        # ④ Classify
        try:
            result = await handler(effect, state)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

        # Hook：只读观察，返回值忽略，异常不得影响运行
        for layer in self.layers:
            try:
                layer.observe(effect, result, state)
            except Exception:  # noqa: BLE001
                pass
        return result

    async def _terminal(self, effect: Effect, state: State) -> Any:
        state.usage["calls"] += 1
        if effect.kind == "model":
            state.usage["tokens"] += 10
        if self.record_only:
            return {"ok": True, "output": f"[dry-run:{effect.kind}]"}
        handler = self.handlers.get(effect.kind)
        if handler is None:
            raise KeyError(f"未注册的效应类型：{effect.kind}")
        return await _maybe(handler(effect, state))

    # ------------------------------------------------------------ 提交
    @staticmethod
    def _commit(state: State, decision: Decision, results: list[Any]) -> None:
        batch: dict[str, Any] = {}
        for effect, result in zip(decision.effects, results):
            key = effect.key or "last"
            state.results[key] = result
            batch[key] = result
            if isinstance(result, dict) and "output" in result:
                state.data["last_output"] = result["output"]
            elif isinstance(result, str):
                state.data["last_output"] = result
        # 每轮覆盖：程序只读 __batch__ 就知道"本批新结果"，
        # 不必在 state 里塞游标，回溯时历史结果仍留在 state.results。
        state.results["__batch__"] = batch
        state.data.update(decision.patch)
        state.rev += 1

    # ------------------------------------------------------------ 内置效应处理器
    async def _model(self, effect: Effect, state: State) -> dict:
        """脚本化模型：脚本内容在 data，消费进度在 journal（不随回溯回滚）。"""

        script = state.data.get("script", [])
        cursor = int(state.journal.get("cursor", 0))
        reply = script[cursor] if cursor < len(script) else {"content": "done"}
        state.journal["cursor"] = cursor + 1
        return {"ok": True, "output": reply}

    async def _tool(self, effect: Effect, state: State) -> dict:
        name = effect.spec["name"]
        fn = state.data["tools"][name]
        out = await _maybe(fn(**effect.spec.get("args", {})))
        return {"ok": True, "output": out}

    async def _skill(self, effect: Effect, state: State) -> dict:
        """渐进披露三段：catalog 常驻 / body 按需 / resource 按需。"""

        catalog = state.data.get("skills", {})
        name, part = effect.spec["name"], effect.spec.get("part", "body")
        if part == "catalog":
            out = {k: v.get("description", "") for k, v in catalog.items()}
        elif part == "resource":
            out = catalog[name]["resources"].get(effect.spec["path"], "")
        else:
            out = catalog[name].get("body", "")
        return {"ok": True, "output": out}

    async def _ask(self, effect: Effect, state: State) -> dict:
        return {"ok": True, "output": {"approved": True, "reason": effect.spec.get("reason", "")}}

    async def _wait(self, effect: Effect, state: State) -> dict:
        """控制权交给外部系统：只在这里等，程序本身不发号施令。"""

        queue = state.data["external_queue"]
        command = await queue.get()
        return {"ok": True, "output": command}

    async def _compute(self, effect: Effect, state: State) -> dict:
        op, args = effect.spec.get("op"), effect.spec.get("args", [])
        out = {
            "concat": lambda: "".join(map(str, args)),
            "upper": lambda: str(args[0]).upper(),
            "sum": lambda: sum(args),
            "join": lambda: " | ".join(map(str, args)),
        }[op]()
        return {"ok": True, "output": out}

    async def _child(self, effect: Effect, state: State) -> dict:
        child_state = State(
            goal=effect.spec.get("goal", state.goal),
            data=copy.deepcopy(effect.spec.get("data", {})),
        )
        out = await self.interpret(effect.spec["program"], child_state)
        return {"ok": out.status in ("completed", "degraded"), "output": out.answer}


__all__ = ["Runtime", "Limits", "Outcome", "GateDenied", "ValidationFailed", "capabilities"]
