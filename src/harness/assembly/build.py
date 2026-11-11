"""装配层：build(cfg) 是唯一实例化处。"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Literal

from harness.parts.actor import Actor
from harness.assembly.agent import Agent
from harness.parts.body import PlanExecutePolicy, ReactPolicy, WorkflowPolicy
from harness.contracts.types import Budget
from harness.parts.context import BudgetedContext
from harness.contracts.types import Step
from harness.parts.delivery import DefaultDelivery
from harness.parts.durability import MemoryDurability
from harness.contracts.errors import ConfigError
from harness.parts.guard import AllowAllGuard
from harness.parts.reflector import NullReflector
from harness.parts.tools import FunctionTool, ToolRegistry, as_tool
from harness.parts.tracer import NullTracer


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
    #: v3.1（SUPPLEMENT A4）：显式 Limits 透传；缺省由 Budget 推导护栏口径。
    limits: Any = None
    #: v3.1（SUPPLEMENT A2）：检查点存储（CheckpointStore 协议），供崩溃恢复。
    checkpoints: Any = None
    #: C05：最终答案出口判定（Validator 协议实现）；None = 不判定。
    validator: Any = None
    #: G07：model_call 插点（callable(ModelRequest) -> ModelResponse）；
    #: None = 直调模型。
    model_call: Any = None


def build(config: AgentConfig) -> Agent:
    # F03：默认即空实现要在装配期显式可见（观测/反思/准入的空默认只
    # 服务测试；生产预设 build_production 已把这些参数全部设为必填）。
    if config.tracer is None:
        warnings.warn("tracer 未指定，默认 NullTracer（无观测）；生产请显式传入",
                      UserWarning, stacklevel=2)
    if config.reflector is None:
        warnings.warn("reflector 未指定，默认 NullReflector（不评估）；生产请显式传入",
                      UserWarning, stacklevel=2)
    if config.guard is None:
        warnings.warn("guard 未指定，默认 AllowAllGuard（全部放行）；生产请显式传入",
                      UserWarning, stacklevel=2)
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
    actor = Actor(model=config.model, tools=registry, resilience=config.resilience,
                  model_call=config.model_call)
    context = config.context or BudgetedContext(system=config.system)

    return Agent(
        name=config.name,
        policy=policy,
        actor=actor,
        context=context,
        guard=config.guard or AllowAllGuard(),
        budget=config.budget or Budget(),
        tracer=config.tracer or NullTracer(),
        # C10：默认改 MemoryDurability（save/load 真实可用，审批挂起/崩溃
        # 恢复成立）。NullDurability 仍可显式传入，但不再是默认。
        durability=config.durability or MemoryDurability(),
        delivery=config.delivery or DefaultDelivery(),
        reflector=config.reflector or NullReflector(),
        max_steps=config.max_steps,
        knowledge=config.knowledge,
        retrieval=config.retrieval,
        memory=config.memory,
        memory_policy=config.memory_policy,
        limits=config.limits,
        checkpoints=config.checkpoints,
        validator=config.validator,
    )
