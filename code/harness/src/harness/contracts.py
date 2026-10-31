"""公开契约：类型、协议、错误。

这一层不依赖任何第三方库，也不 import 具体组件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from .state import State


# ---------------------------------------------------------------- 状态与结果


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    REFUSED = "refused"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Goal:
    text: str
    user_id: str = "anonymous"
    session_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionRef:
    session_id: str
    tenant: str = "default"
    started_at: str = ""


@dataclass
class Step:
    id: str
    instruction: str = ""
    tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    idem_key: str | None = None
    kind: Literal["tool", "llm", "agent", "human"] = "tool"


@dataclass
class Done:
    answer: str = ""
    reason: str = "completed"


@dataclass
class ActionResult:
    step_id: str
    ok: bool
    output: str = ""
    error: str | None = None
    tokens: int = 0
    tool_name: str | None = None
    citations: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    passed: bool
    reason: str = ""
    action: Literal["accept", "retry", "patch", "replan_all"] = "accept"


@dataclass
class Plan:
    id: str
    steps: list[Step] = field(default_factory=list)
    rev: int = 0


@dataclass
class Recalled:
    text: str
    layer: Literal["semantic", "episodic", "procedural"] = "semantic"
    score: float = 0.0
    source: str = ""
    age_days: int = 0


@dataclass
class Pack:
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)


@dataclass
class Brief:
    goal: Goal
    context_refs: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    deadline: float | None = None


@dataclass
class Board:
    state: State
    rev: int = 0
    owner: str | None = None


@dataclass(frozen=True)
class Route:
    name: str
    accepts: list[str] = field(default_factory=list)
    fallback: bool = False


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


@dataclass(frozen=True)
class GuardDecision:
    action: Literal["allow", "deny", "ask"]
    reason: str = ""
    card: dict[str, Any] = field(default_factory=dict)
    expires_in: int | None = None

    @classmethod
    def allow(cls) -> "GuardDecision":
        return cls("allow")

    @classmethod
    def deny(cls, reason: str) -> "GuardDecision":
        return cls("deny", reason=reason)

    @classmethod
    def ask(cls, reason: str, card: dict[str, Any] | None = None,
            expires_in: int | None = None) -> "GuardDecision":
        return cls("ask", reason=reason, card=card or {}, expires_in=expires_in)


@dataclass
class ApprovalRequest:
    id: str
    step: Step
    reason: str
    card: dict[str, Any] = field(default_factory=dict)
    expires_at: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class Decision:
    action: Literal["approve", "reject", "modify"]
    by: str = "human"
    reason: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def approve(cls, by: str = "human", comment: str = "") -> "Decision":
        return cls("approve", by=by, reason=comment)

    @classmethod
    def reject(cls, by: str = "human", reason: str = "") -> "Decision":
        return cls("reject", by=by, reason=reason)

    @classmethod
    def modify(cls, args: dict[str, Any], by: str = "human") -> "Decision":
        return cls("modify", by=by, args=args)


@dataclass
class TraceEvent:
    trace_id: str
    span_id: str
    name: str
    kind: str = "span"
    parent_id: str | None = None
    start_ms: int = 0
    end_ms: int = 0
    fields: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- 协议


@runtime_checkable
class Model(Protocol):
    async def complete(self, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]] | None = None) -> ModelReply: ...


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    async def invoke(self, args: dict[str, Any]) -> str: ...


@runtime_checkable
class BodyPolicy(Protocol):
    async def next_step(self, state: "State", ctx: "RunContext") -> Step | Done: ...


@runtime_checkable
class Planner(Protocol):
    async def plan(self, goal: Goal, state: "State") -> Plan: ...


@runtime_checkable
class Guard(Protocol):
    async def check(self, step: Step, state: "State") -> GuardDecision: ...


@runtime_checkable
class Reflector(Protocol):
    async def review(self, result: ActionResult, state: "State") -> Verdict: ...


@runtime_checkable
class Context(Protocol):
    async def assemble(self, state: "State", budget_tokens: int) -> Pack: ...


@runtime_checkable
class Knowledge(Protocol):
    async def retrieve(self, query: str, *, k: int,
                       filters: dict[str, Any] | None = None) -> list[Recalled]: ...


@runtime_checkable
class Memory(Protocol):
    async def recall(self, query: str, *, scope: str,
                     layers: list[str], k: int) -> list[Recalled]: ...

    async def write(self, items: list[Recalled]) -> int: ...


@runtime_checkable
class Tracer(Protocol):
    async def emit(self, event: TraceEvent) -> None: ...


@runtime_checkable
class Durability(Protocol):
    async def save(self, state: "State") -> None: ...

    async def load(self, session_id: str) -> "State | None": ...


@runtime_checkable
class Delivery(Protocol):
    async def finish(self, state: "State", status: RunStatus, *,
                     answer: str = "", error: str | None = None,
                     pending: ApprovalRequest | None = None) -> "RunResult": ...


@runtime_checkable
class Router(Protocol):
    async def route(self, goal: Goal) -> Route: ...


@runtime_checkable
class Runnable(Protocol):
    name: str

    async def run(self, goal: Goal,
                  session: SessionRef | None = None) -> "RunResult": ...


@dataclass
class RunContext:
    """一次运行内部的服务定位器；只给 BodyPolicy 用，不对外公开。"""

    state: "State"
    actor: Any
    context: Context
    budget: Any
    tracer: Tracer
    knowledge: Knowledge | None = None
    memory: Memory | None = None
    skills: Any = None
    config: Any = None
