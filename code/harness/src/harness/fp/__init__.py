"""L5 门面：组合式 API（SPEC §18）。

三个类型，语义定死：
    Layer    单一扩展单元；`>>` 左为外层，`|` 回退
    Program  策略单元 = body + 若干层
    Harness  能力容器；`run(program, goal)`

Program 里没有实例，能力全在 Harness——这是"换后端不改程序"的类型级保证。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from harness.contracts.errors import ConfigError
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.types import (
    Budget,
    Effect,
    Goal,
    LayerSpec,
    ProgramSpec,
    SessionRef,
)
from harness.kernel import chain
from harness.kernel.loop import run_loop
from harness.kernel.scope import Namespace, RunScope
from harness.parts.actor_v2 import LlmActor
from harness.parts.framing import ChatEncoder, ModelFramer
from harness.parts.middleware.base import Layer, layer
from harness.parts.policy import PlanExecutePolicy, ReactPolicy, WorkflowPolicy
from harness.parts.tools import ToolRegistry


class NotSerializable(ConfigError):
    """闭包层无法序列化——不假装可以。"""


# ------------------------------------------------------------------ 组合


def compose(*layers: Layer) -> Layer:
    """把若干层合成一层；顺序仍由各层的 after/before 在 resolve 时拓扑排序。"""
    if not layers:
        raise ValueError("compose 至少需要一个层")
    if len(layers) == 1:
        return layers[0]

    names = [lay.name for lay in layers]
    first, rest = layers[0], layers[1:]

    def build(nxt):
        handler = nxt
        for lay in reversed(rest):
            handler = lay.build(handler)
        return first.build(handler)

    return Layer(
        name=" >> ".join(names),
        points=frozenset().union(*(lay.points for lay in layers)),
        build=build,
        needs=frozenset().union(*(lay.needs for lay in layers)),
        after=frozenset().union(*(lay.after - set(names) for lay in layers)),
        before=frozenset().union(*(lay.before - set(names) for lay in layers)),
    )


def fallback(left: Layer, right: Layer) -> Layer:
    """回退：前者抛错则整体改用后者，二者共享同一内层。"""

    def build(nxt):
        inner_left, inner_right = left.build(nxt), right.build(nxt)

        async def handler(req):
            try:
                return await inner_left(req)
            except Exception:  # noqa: BLE001 - 回退边界
                return await inner_right(req)

        return handler

    return Layer(
        name=f"{left.name} | {right.name}",
        points=left.points | right.points,
        build=build,
        needs=left.needs | right.needs,
    )


def describe(program: "Program") -> str:
    """打印**解析后**的层顺序（组合看不见顺序，必须能打印）。"""
    parts = [getattr(program.body, "name", type(program.body).__name__)]
    for point in ("run", "step", "model_call", "tool_call"):
        names = [lay.name for lay in chain.resolve(program.layers, point)]
        if names:
            parts.append(f"{point}: " + " > ".join(names))
    return " | ".join(parts)


# ------------------------------------------------------------------ Program


@dataclass(frozen=True)
class Program:
    body: Any
    max_steps: int = 24
    layers: tuple[Layer, ...] = ()

    def __rshift__(self, lay: Layer) -> "Program":
        return replace(self, layers=self.layers + (lay,))

    def to_spec(self) -> ProgramSpec:
        specs: list[LayerSpec] = []
        for lay in self.layers:
            spec = getattr(lay, "spec", None)
            if spec is None:
                raise NotSerializable(f"层 {lay.name} 没有声明形态，无法序列化（闭包不可序列化）")
            specs.append(spec)
        return ProgramSpec(
            body=getattr(self.body, "name", "react"),
            max_steps=self.max_steps,
            layers=tuple(specs),
        )

    @classmethod
    def from_spec(cls, spec: ProgramSpec, *, factories: dict[str, Any]) -> "Program":
        """由声明形态重建；未知层名 → ConfigError（不静默跳过）。"""
        layers = []
        for layer_spec in spec.layers:
            factory = factories.get(layer_spec.name)
            if factory is None:
                raise ConfigError(f"未知层：{layer_spec.name}；可用：{sorted(factories)}")
            layers.append(factory(**layer_spec.config))
        body = {"react": ReactPolicy, "workflow": WorkflowPolicy}.get(spec.body)
        if body is None:
            raise ConfigError(f"未知 body：{spec.body}")
        return cls(body=body(), max_steps=spec.max_steps, layers=tuple(layers))


# ------------------------------------------------------------------ 工厂


def react(*, max_steps: int = 24) -> Program:
    return Program(body=ReactPolicy(), max_steps=max_steps)


def workflow(*steps, max_steps: int | None = None) -> Program:
    return Program(
        body=WorkflowPolicy(steps=list(steps)),
        max_steps=max_steps or (len(steps) + 1),
    )


def pe(planner, *, max_steps: int = 24) -> Program:
    return Program(body=PlanExecutePolicy(planner=planner), max_steps=max_steps)


from harness.assembly.harness import Harness  # noqa: E402  （能力容器属装配层）


__all__ = [
    "Layer",
    "layer",
    "compose",
    "fallback",
    "describe",
    "Program",
    "react",
    "workflow",
    "pe",
    "Harness",
    "NotSerializable",
]
