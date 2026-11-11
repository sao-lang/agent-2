"""agent-harness：可组合的 agent 基座。

公开 API 只承诺这一层；内部按六层组织：
    contracts（契约） · kernel（内核） · parts（部件）
    impl（实现） · assembly（装配） · fp（门面）

单版本收敛（AUDIT BL-2/BL-3）：只导出门面入口——
``Harness`` / ``build_harness`` / ``HarnessConfig`` / fp 组合子。
"""

from __future__ import annotations

from harness.assembly.config import HarnessConfig, build_harness
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
from harness.contracts.types import Budget
from harness.parts.context import BudgetedContext, NullContext
from harness.parts.delivery import DefaultDelivery
from harness.parts.dispatch import AlwaysRoute, RuleRouter
from harness.parts.durability import MemoryDurability, NullDurability, SQLiteDurability
from harness.parts.guard import AllowAllGuard, AnswerValidator, DenyAllGuard, FunctionGuard, SessionGuard
from harness.parts.knowledge import InMemoryKnowledge
from harness.parts.memory import InMemoryMemory
from harness.parts.policy import (
    FunctionPlanner,
    PlanExecutePolicy,
    ReactPolicy,
    ScriptedPlanner,
    WorkflowPolicy,
)
from harness.parts.reflector import FunctionReflector, NullReflector
from harness.parts.resilience import CircuitBreaker, CircuitOpen, Resilience
from harness.parts.structured import StructuredModel, structured, validate_json
from harness.parts.retrieval import AutoRetrieval, NoRetrieval
from harness.parts.skills import Skill, SkillMeta, SkillRegistry
from harness.parts.tools import FunctionTool, ToolRegistry, as_tool, tool
from harness.parts.topology import Blackboard, Handoff, Pipeline, Supervisor
from harness.parts.sinks import JsonlSink, MemorySink, NullSink
from harness.parts.middleware.base import Layer, layer
from harness.contracts.protocols.runtime import Hook

# ---- 通用解释器与效应系统（PROPOSAL §9.2） ----
# 顶层 `Decision` 是既有「人工审批结果」类型（审批恢复流依赖），不能覆盖；
# 转移决策以 `Transition` 别名导出，原名见 harness.contracts.decision.Decision。
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
    RuntimeLimits,
    Outcome,
    Runtime,
    ValidationFailed,
    interpret,
)
from harness.fp import (
    Harness,
    Program,
    compose,
    describe,
    fallback,
    pe,
    react,
    workflow,
)
from harness.fp import frontends as _frontends  # noqa: F401 （触发前端自注册）
from harness.adapters import openai as _openai_adapter  # noqa: F401 （B08：适配器自注册）

__version__ = "0.3.0"
contracts_version = "3"

__all__ = [
    "ActionResult", "AllowAllGuard", "AlwaysRoute",
    "ApprovalExpired", "ApprovalRequest", "AutoRetrieval", "Blackboard", "Board", "Brief",
    "Budget", "BudgetExceeded", "BudgetedContext", "ConfigError", "ContractError",
    "Decision", "DefaultDelivery", "DenyAllGuard", "Done", "FunctionGuard",
    "FunctionPlanner", "FunctionReflector", "FunctionTool", "Goal", "GuardDecision",
    "GuardDenied", "Handoff", "Harness", "HarnessConfig", "InMemoryKnowledge",
    "InMemoryMemory", "JsonlSink",
    "MaxStepsExceeded", "MemoryDurability", "MemorySink", "ModelReply", "NullContext",
    "NullDurability", "NullReflector", "NullSink", "NoRetrieval", "Pack", "Pipeline",
    "Plan", "PlanExecutePolicy", "Program", "ReactPolicy", "Recalled", "ReflectorReject",
    "Resilience", "Route", "RuleRouter", "RunResult", "RunStatus", "SQLiteDurability",
    "ScriptedPlanner", "SessionRef", "Skill", "SkillMeta", "SkillRegistry", "State",
    "Step", "Supervisor", "ToolCall", "ToolError", "ToolRegistry", "Verdict",
    "WorkflowPolicy", "as_tool", "build_harness", "compose", "contracts_version",
    "describe", "fallback", "interpret", "layer", "pe", "react", "tool", "workflow",
    # C01/C02/C03/C05/C08：新增出口判定、会话准入、熔断与结构化输出
    "AnswerValidator", "SessionGuard", "CircuitBreaker", "CircuitOpen",
    "StructuredModel", "structured", "validate_json",
    # 解释器与组合子
    "Transition", "Halt", "FnProgram", "Runtime", "Outcome",
    "RuntimeLimits", "ValidationFailed", "EffectLayer", "execute_effects",
    "Effect", "capabilities", "program_describe", "program_to_spec",
    "Layer", "Hook",
]
