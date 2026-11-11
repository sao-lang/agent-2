"""agent-harness：可组合的 agent 基座。

公开 API 只承诺这一层；内部按六层组织：
    contracts（契约） · kernel（内核） · parts（部件）
    impl（实现） · assembly（装配） · fp（门面）
"""

from __future__ import annotations

from harness.assembly.build import AgentConfig, build
from harness.assembly.presets import (
    build_minimal,
    build_pe,
    build_production,
    build_react,
    build_workflow,
)
from harness.contracts.errors import (
    ApprovalExpired,
    BudgetExceeded,
    ConfigError,
    ContractError,
    GuardDenied,
    HarnessError,
    MaxStepsExceeded,
    ReflectorReject,
    ToolError,
)
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.types import (
    ActionResult,
    ApprovalRequest,
    Board,
    Brief,
    Decision,
    Done,
    Goal,
    GuardDecision,
    ModelReply,
    Pack,
    Plan,
    Recalled,
    Route,
    RunStatus,
    SessionRef,
    Step,
    ToolCall,
    Verdict,
)
from harness.assembly.agent import Agent
from harness.parts.actor import Actor
from harness.parts.body import (
    FunctionPlanner,
    PlanExecutePolicy,
    ReactPolicy,
    ScriptedPlanner,
    WorkflowPolicy,
)
from harness.parts.budget import Budget
from harness.parts.context import BudgetedContext, NullContext
from harness.parts.delivery import DefaultDelivery
from harness.parts.dispatch import AlwaysRoute, RuleRouter
from harness.parts.durability import MemoryDurability, NullDurability, SQLiteDurability
from harness.parts.guard import AllowAllGuard, DenyAllGuard, FunctionGuard
from harness.parts.knowledge import InMemoryKnowledge
from harness.parts.memory import InMemoryMemory
from harness.parts.reflector import FunctionReflector, NullReflector
from harness.parts.resilience import Resilience
from harness.parts.retrieval import AutoRetrieval, NoRetrieval
from harness.parts.skills import Skill, SkillMeta, SkillRegistry
from harness.parts.tools import FunctionTool, ToolRegistry, as_tool, tool
from harness.parts.topology import Blackboard, Handoff, Pipeline, Supervisor
from harness.parts.tracer import JsonlTracer, MemoryTracer, NullTracer
from harness.parts.middleware.base import Layer, layer
from harness.contracts.protocols.runtime import Hook

# ---- v3：通用解释器与效应系统（PROPOSAL §9.2，纯新增） ----
# 顶层 `Decision` 是既有「人工审批结果」类型（ApprovalChannel / Agent.resume
# 依赖），不能覆盖；转移决策以 `Transition` 别名导出，原名见
# harness.contracts.decision.Decision。
from harness.contracts.decision import (
    Decision as Transition,
    FnProgram,
    Halt,
    capabilities,
    describe as program_describe,
    to_spec as program_to_spec,
)
from harness.kernel.effects import EffectLayer, execute_effects
from harness.contracts.types import Effect
from harness.kernel.interpret import (
    Limits as InterpreterLimits,
    Outcome,
    Runtime,
    ValidationFailed,
    interpret,
)
from harness.fp import frontends as _frontends  # noqa: F401 （触发前端自注册）

__version__ = "0.3.0"
contracts_version = "3"

__all__ = [
    "ActionResult", "Actor", "Agent", "AgentConfig", "AllowAllGuard", "AlwaysRoute",
    "ApprovalExpired", "ApprovalRequest", "AutoRetrieval", "Blackboard", "Board", "Brief",
    "Budget", "BudgetExceeded", "BudgetedContext", "ConfigError", "ContractError",
    "Decision", "DefaultDelivery", "DenyAllGuard", "Done", "FunctionGuard",
    "FunctionPlanner", "FunctionReflector", "FunctionTool", "Goal", "GuardDecision",
    "GuardDenied", "Handoff", "InMemoryKnowledge", "InMemoryMemory", "JsonlTracer",
    "MaxStepsExceeded", "MemoryDurability", "MemoryTracer", "ModelReply", "NullContext",
    "NullDurability", "NullReflector", "NullTracer", "NoRetrieval", "Pack", "Pipeline",
    "Plan", "PlanExecutePolicy", "ReactPolicy", "Recalled", "ReflectorReject",
    "Resilience", "Route", "RuleRouter", "RunResult", "RunStatus", "SQLiteDurability",
    "ScriptedPlanner", "SessionRef", "Skill", "SkillMeta", "SkillRegistry", "State",
    "Step", "Supervisor", "ToolCall", "ToolError", "ToolRegistry", "Verdict",
    "WorkflowPolicy", "as_tool", "build", "build_minimal", "build_pe",
    "build_production", "build_react", "build_workflow", "contracts_version", "tool",
    # v3
    "Transition", "Halt", "FnProgram", "interpret", "Runtime", "Outcome",
    "InterpreterLimits", "ValidationFailed", "EffectLayer", "execute_effects",
    "Effect", "capabilities", "program_describe", "program_to_spec",
    "Layer", "layer", "Hook",
]
