"""装配层：build(cfg) 是唯一实例化处。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .actor import Actor
from .agent import Agent
from .body import PlanExecutePolicy, ReactPolicy, WorkflowPolicy
from .budget import Budget
from .context import BudgetedContext
from .contracts import Step
from .delivery import DefaultDelivery
from .durability import NullDurability
from .errors import ConfigError
from .guard import AllowAllGuard
from .reflector import NullReflector
from .tools import FunctionTool, ToolRegistry, as_tool
from .tracer import NullTracer


@dataclass
class AgentConfig:
    model: Any
    tools: list[FunctionTool] = field(default_factory=list)
    mode: Literal["react", "workflow", "pe"] = "react"
    workflow: list[Step] | None = None
    planner: Any = None
    max_steps: int = 12
    system: str = ""
    guard: Any = None
    budget: Budget | None = None
    tracer: Any = None
    durability: Any = None
    delivery: Any = None
    reflector: Any = None
    context: Any = None
    resilience: Any = None
    knowledge: Any = None
    retrieval: Any = None
    memory: Any = None
    memory_policy: dict[str, Any] | None = None
    name: str = "agent"


def build(config: AgentConfig) -> Agent:
    if config.mode == "workflow":
        if not config.workflow:
            raise ConfigError("mode=workflow 需要 workflow 步骤")
        if config.planner is not None:
            raise ConfigError("mode=workflow 不允许 planner")
        policy = WorkflowPolicy(config.workflow)
    elif config.mode == "react":
        if config.workflow:
            raise ConfigError("mode=react 不允许 workflow")
        if config.planner is not None:
            raise ConfigError("mode=react 不允许 planner")
        policy = ReactPolicy(max_steps=config.max_steps)
    elif config.mode == "pe":
        if config.workflow is not None:
            raise ConfigError("mode=pe 不允许 workflow")
        if config.planner is None:
            raise ConfigError("mode=pe 需要 planner")
        policy = PlanExecutePolicy(config.planner, max_steps=config.max_steps)
    else:
        raise ConfigError(f"未知 mode：{config.mode}")

    registry = ToolRegistry().add(*(as_tool(item) for item in config.tools))
    actor = Actor(model=config.model, tools=registry, resilience=config.resilience)
    context = config.context or BudgetedContext(system=config.system)

    return Agent(
        name=config.name,
        policy=policy,
        actor=actor,
        context=context,
        guard=config.guard or AllowAllGuard(),
        budget=config.budget or Budget(),
        tracer=config.tracer or NullTracer(),
        durability=config.durability or NullDurability(),
        delivery=config.delivery or DefaultDelivery(),
        reflector=config.reflector or NullReflector(),
        max_steps=config.max_steps,
        knowledge=config.knowledge,
        retrieval=config.retrieval,
        memory=config.memory,
        memory_policy=config.memory_policy,
    )
