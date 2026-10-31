"""agent-harness：可组合的 agent 基座。

公开 API 只承诺这一层；内部组件按需从子模块导入。
"""

from __future__ import annotations

from .actor import Actor
from .agent import Agent
from .budget import Budget
from .build import AgentConfig, build
from .body import FunctionPlanner, PlanExecutePolicy, ScriptedPlanner
from .context import BudgetedContext, NullContext
from .contracts import (
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
from .delivery import DefaultDelivery
from .dispatch import AlwaysRoute, RuleRouter
from .durability import MemoryDurability, NullDurability, SQLiteDurability
from .errors import ApprovalExpired, BudgetExceeded, ConfigError, HarnessError
from .guard import AllowAllGuard, DenyAllGuard, FunctionGuard
from .knowledge import InMemoryKnowledge
from .memory import InMemoryMemory
from .presets import build_minimal, build_pe, build_production, build_react, build_workflow
from .reflector import FunctionReflector, NullReflector
from .retrieval import AutoRetrieval, NoRetrieval
from .result import RunResult
from .resilience import Resilience
from .skills import Skill, SkillMeta, SkillRegistry
from .state import State
from .topology import Blackboard, Handoff, Pipeline, Supervisor
from .tools import FunctionTool, ToolRegistry, as_tool, tool
from .tracer import JsonlTracer, MemoryTracer, NullTracer

__version__ = "0.1.0"
contracts_version = "1"

__all__ = [
    "ActionResult",
    "Actor",
    "Agent",
    "AgentConfig",
    "AllowAllGuard",
    "AlwaysRoute",
    "ApprovalExpired",
    "ApprovalRequest",
    "AutoRetrieval",
    "Blackboard",
    "Board",
    "Brief",
    "Budget",
    "BudgetExceeded",
    "BudgetedContext",
    "ConfigError",
    "Decision",
    "DefaultDelivery",
    "DenyAllGuard",
    "Done",
    "FunctionGuard",
    "FunctionPlanner",
    "FunctionReflector",
    "FunctionTool",
    "Goal",
    "GuardDecision",
    "Handoff",
    "JsonlTracer",
    "InMemoryKnowledge",
    "InMemoryMemory",
    "MemoryDurability",
    "MemoryTracer",
    "ModelReply",
    "NullContext",
    "NullDurability",
    "NullReflector",
    "NullTracer",
    "NoRetrieval",
    "Pack",
    "Pipeline",
    "Plan",
    "PlanExecutePolicy",
    "Recalled",
    "Resilience",
    "Route",
    "RuleRouter",
    "RunResult",
    "RunStatus",
    "ScriptedPlanner",
    "SessionRef",
    "Skill",
    "SkillMeta",
    "SkillRegistry",
    "State",
    "SQLiteDurability",
    "Step",
    "Supervisor",
    "ToolCall",
    "ToolRegistry",
    "Verdict",
    "as_tool",
    "build",
    "build_minimal",
    "build_pe",
    "build_production",
    "build_react",
    "build_workflow",
    "contracts_version",
    "tool",
]
