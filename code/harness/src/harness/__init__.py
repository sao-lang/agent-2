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

__version__ = "0.2.0"
contracts_version = "2"

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
]
