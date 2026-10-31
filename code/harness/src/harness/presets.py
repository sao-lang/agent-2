"""五个装配预设：最小、循环、工作流、P&E、生产。

预设不是“另一套实现”，只是 AgentConfig 的简写；换预设只改配置。
"""

from __future__ import annotations

from typing import Any

from .build import AgentConfig, build


def build_minimal(*, model, tools=None, **kwargs) -> Any:
    return build(AgentConfig(model=model, tools=list(tools or []), mode="react", **kwargs))


def build_react(*, model, tools=None, budget=None, tracer=None, guard=None,
                durability=None, **kwargs) -> Any:
    return build(AgentConfig(
        model=model,
        tools=list(tools or []),
        mode="react",
        budget=budget,
        tracer=tracer,
        guard=guard,
        durability=durability,
        **kwargs,
    ))


def build_workflow(*, model, workflow, tools=None, **kwargs) -> Any:
    return build(AgentConfig(
        model=model,
        tools=list(tools or []),
        mode="workflow",
        workflow=list(workflow),
        **kwargs,
    ))


def build_pe(*, model, planner, tools=None, **kwargs) -> Any:
    return build(AgentConfig(
        model=model,
        tools=list(tools or []),
        mode="pe",
        planner=planner,
        **kwargs,
    ))


def build_production(*, model, tools=None, guard, budget, tracer, durability,
                     delivery=None, reflector=None, knowledge=None,
                     retrieval=None, memory=None, memory_policy=None,
                     **kwargs) -> Any:
    return build(AgentConfig(
        model=model,
        tools=list(tools or []),
        mode="react",
        guard=guard,
        budget=budget,
        tracer=tracer,
        durability=durability,
        delivery=delivery,
        reflector=reflector,
        knowledge=knowledge,
        retrieval=retrieval,
        memory=memory,
        memory_policy=memory_policy,
        **kwargs,
    ))
