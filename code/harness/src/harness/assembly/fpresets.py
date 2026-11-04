"""五个预设：配置简写，不是另一套实现（SPEC M15.6）。"""

from __future__ import annotations

from typing import Any

from harness.assembly.config import BackendSpec, HarnessConfig, StoreSpec
from harness.contracts.types import Budget, Step


def _base(**kwargs: Any) -> HarnessConfig:
    return HarnessConfig(**kwargs)


def minimal(*, model: Any = "fake", tools: tuple[Any, ...] = ()) -> HarnessConfig:
    """冒烟测试：无任何横切层。"""
    return _base(model=model, tools=tools, layers=(), budget=Budget(tokens=8_000, calls=8))


def react(*, model: Any = "fake", tools: tuple[Any, ...] = (), budget: Budget | None = None) -> HarnessConfig:
    """普通对话/工具 agent：预算 + 任务板。"""
    return _base(
        model=model,
        tools=tools,
        budget=budget or Budget(tokens=100_000, calls=40),
        layers=(),     # 层在 Program 里声明；这里只给能力
    )


def workflow(*, model: Any = "fake", tools: tuple[Any, ...] = ()) -> HarnessConfig:
    return _base(model=model, tools=tools, budget=Budget(tokens=40_000, calls=20))


def pe(*, model: Any = "fake", tools: tuple[Any, ...] = ()) -> HarnessConfig:
    return _base(model=model, tools=tools, budget=Budget(tokens=80_000, calls=30))


def production(*, model: Any = "fake", tools: tuple[Any, ...] = ()) -> HarnessConfig:
    """生产形态：全部能力打开。"""
    return _base(
        model=model,
        tools=tools,
        stores=StoreSpec(durability="memory", memory="memory"),
        backends=BackendSpec(fs="memory", sandbox="fake", artifacts="memory",
                             secrets="env", index="memory"),
        guardrails=("injection", "pii", "secret_leak"),
        budget=Budget(tokens=400_000, calls=120),
        max_depth=2,
    )


__all__ = ["minimal", "react", "workflow", "pe", "production"]
