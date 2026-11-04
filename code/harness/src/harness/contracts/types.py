"""契约数据类型（SPEC M1.2 / M1.4）。

规则：进契约的 dataclass 一律 `frozen=True`（`State`、`Step`、`Plan`、`RunContext`、
`Budget` 与流式累积态除外，它们跨层演进）。只增不改：新增字段必须有默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from harness.contracts.events import EVENT_NAMES, HookEvent, RunEvent, Span, TraceEvent
from harness.contracts.protocols import *  # noqa: F401,F403  （兼容：旧代码从 types 取协议）
from harness.contracts.protocols import Handler
from harness.contracts.status import (
    TERMINAL_STATUSES,
    FrameKind,
    Gate5,
    GuardAction,
    GuardrailAction,
    Phase,
    Point,
    RunStatus,
    SideEffect,
)

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.state import State

RunId = str
TraceId = str


# ------------------------------------------------------------------ 标识


@dataclass(frozen=True)
class Namespace:
    """四段元组而非字符串：任何一层隔离都不能靠拼字符串（SPEC M1.11）。"""

    tenant: str = "default"
    user: str = "anonymous"
    session: str = "default"
    agent: str = "agent"

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.tenant, self.user, self.session, self.agent)

    def child(self, agent: str) -> "Namespace":
        return Namespace(self.tenant, self.user, self.session, agent)


@dataclass(frozen=True)
class SessionRef:
    """持久化单位（一个键），横跨多次 loop，挂不到任何插点。"""

    session_id: str
    tenant: str = "default"
    started_at: str = ""


@dataclass(frozen=True)
class SessionMeta:
    id: str
    tenant: str = "default"
    user_id: str = "anonymous"
    title: str = ""
    status: str = "active"
    created_at: float = 0.0
    last_active: float = 0.0
    quota: dict[str, int] = field(default_factory=dict)
    pinned_model: str | None = None


# ------------------------------------------------------------------ 输入


@dataclass(frozen=True)
class Goal:
    text: str
    user_id: str = "anonymous"
    session_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Brief:
    """子 agent 的交接单：必须带原始依据，不许只带结论（SPEC M14.3）。"""

    goal: Goal
    context_refs: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    deadline: float | None = None


@dataclass(frozen=True)
class TaskSpec:
    description: str
    agent_type: str = "default"
    expected_schema: dict[str, Any] | None = None
    max_steps: int | None = None


# ------------------------------------------------------------------ 过程


@dataclass
class Step:
    id: str
    instruction: str = ""
    tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    idem_key: str | None = None
    kind: Literal["tool", "llm", "agent", "human"] = "tool"
    index: int = 0
    plan_id: str = ""


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str = ""


@dataclass(frozen=True)
class Done:
    answer: str = ""
    reason: str = "completed"


@dataclass
class Plan:
    id: str
    steps: list[Step] = field(default_factory=list)
    rev: int = 0


@dataclass(frozen=True)
class ModelReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"


@dataclass(frozen=True)
class ModelDelta:
    kind: Literal["text", "tool_call", "usage"] = "text"
    text: str = ""
    index: int = 0
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ResponseFormat:
    kind: Literal["text", "json_schema"] = "text"
    schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    tool_call_id: str = ""
    name: str = ""


# ------------------------------------------------------------------ 判定


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str = ""
    action: Literal["accept", "retry", "patch", "replan_all"] = "accept"


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
    def ask(
        cls,
        reason: str,
        card: dict[str, Any] | None = None,
        expires_in: int | None = None,
    ) -> "GuardDecision":
        return cls("ask", reason=reason, card=card or {}, expires_in=expires_in)


@dataclass(frozen=True)
class Content:
    """护栏的输入：文本 + 种类 + 来源引用（SPEC M9.2）。"""

    text: str
    kind: str = "model"
    ref: str = ""


@dataclass(frozen=True)
class GuardrailVerdict:
    """检测与动作分离：检测器只报风险，动作由策略定（SPEC M9.2）。"""

    risk: float = 0.0
    labels: tuple[str, ...] = ()
    action: Literal["allow", "warn", "redact", "rewrite", "ask", "block"] = "allow"
    spans: tuple[tuple[int, int], ...] = ()
    replacement: str | None = None


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


@dataclass(frozen=True)
class Failure:
    """`Filter` 的唯一产物（SPEC M16.1.1）。"""

    status: RunStatus
    reason: str
    retryable: bool = False


# ------------------------------------------------------------------ 结果


@dataclass(frozen=True)
class ActionResult:
    step_id: str
    ok: bool
    output: str = ""
    error: str | None = None
    tokens: int = 0
    tool_name: str | None = None
    citations: list[str] = field(default_factory=list)
    artifacts: list["ArtifactRef"] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResult:
    step_id: str
    tool: str = ""
    ok: bool = True
    output: str = ""
    error: str | None = None
    tokens: int = 0
    artifacts: list["ArtifactRef"] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecResult:
    exit: int = 0
    stdout: str = ""
    stderr: str = ""
    artifacts: list["ArtifactRef"] = field(default_factory=list)
    truncated: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class Pack:
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    frame: "Frame | None" = None


@dataclass(frozen=True)
class Recalled:
    text: str
    layer: Literal["semantic", "episodic", "procedural"] = "semantic"
    score: float = 0.0
    source: str = ""
    age_days: int = 0
    dedup_key: str = ""
    id: str = ""
    superseded_by: str = ""


# ------------------------------------------------------------------ 视图


@dataclass(frozen=True)
class Section:
    """取景产物的一个槽位。`ephemeral` = 只本轮可见（SPEC M6.1）。"""

    name: str
    priority: int = 0
    source: str = ""
    text: str = ""
    tokens_est: int = 0
    ephemeral: bool = False


@dataclass(frozen=True)
class Frame:
    kind: FrameKind = FrameKind.MODEL
    sections: tuple[Section, ...] = ()
    dropped: tuple[str, ...] = ()
    tokens_est: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Card:
    title: str = ""
    body: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    actions: tuple[str, ...] = ()


# ------------------------------------------------------------------ 治理


@dataclass
class Budget:
    tokens: int = 200_000
    calls: int = 60
    used_tokens: int = 0
    used_calls: int = 0
    owner: str = "run"
    retries: int = 0
    replans: int = 0

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.tokens - self.used_tokens)

    @property
    def remaining_calls(self) -> int:
        return max(0, self.calls - self.used_calls)

    @property
    def exhausted(self) -> bool:
        return self.remaining_tokens <= 0 or self.remaining_calls <= 0

    def spend(self, tokens: int = 0, calls: int = 1) -> None:
        self.used_tokens += max(0, tokens)
        self.used_calls += max(0, calls)

    def snapshot(self) -> dict[str, int]:
        return {
            "tokens": self.tokens,
            "calls": self.calls,
            "used_tokens": self.used_tokens,
            "used_calls": self.used_calls,
        }

    def split(self, fraction: float = 0.3) -> "Budget":
        """给子 agent：额度按比例切分，消耗仍计入父（不变量 2）。"""
        ratio = max(0.0, min(1.0, fraction))
        return Budget(
            tokens=int(self.remaining_tokens * ratio),
            calls=max(1, int(self.remaining_calls * ratio)),
            owner=f"child:{self.owner}",
        )


@dataclass(frozen=True)
class Limits:
    cpu_s: float = 10.0
    mem_mb: int = 512
    wall_s: float = 30.0
    output_bytes: int = 1_000_000
    network: bool = False


@dataclass(frozen=True)
class Mount:
    target: str
    source: str | None = None
    mode: Literal["ro", "rw"] = "ro"


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    step: Step
    reason: str = ""
    card: dict[str, Any] = field(default_factory=dict)
    expires_at: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class Checkpoint:
    session_id: str
    rev: int
    state: Any = None
    created_at: float = 0.0


@dataclass(frozen=True)
class Recorded:
    key: str
    value: Any = None
    at: float = 0.0


@dataclass(frozen=True)
class Page:
    items: tuple[Any, ...] = ()
    cursor: str | None = None


# ------------------------------------------------------------------ 工具元数据


@dataclass(frozen=True)
class ToolSpec:
    """工具元数据：驱动审批分级、幂等要求、沙箱路由（SPEC M3.5）。"""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    side_effects: SideEffect = SideEffect.PURE
    scopes: frozenset[str] = frozenset()
    timeout_s: float | None = None
    idempotent: bool = False
    max_output_bytes: int = 32_000
    needs_approval: bool = False
    sandbox: bool = False


@dataclass(frozen=True)
class ToolContext:
    """能力按 `spec.scopes` 注入；工具只能拿到声明过的能力。"""

    fs: Any = None
    sandbox: Any = None
    artifacts: Any = None
    secrets: Any = None
    state: Any = None
    signal: Any = None


# ------------------------------------------------------------------ 后端数据


@dataclass(frozen=True)
class Document:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    not_before: float = 0.0
    attempts: int = 0
    dedup_key: str = ""


@dataclass(frozen=True)
class Match:
    path: str
    line: int = 0
    text: str = ""


@dataclass(frozen=True)
class Stat:
    path: str
    size: int = 0
    mtime: float = 0.0
    mode: int = 0
    is_dir: bool = False


@dataclass(frozen=True)
class ArtifactRef:
    uri: str
    bytes: int = 0
    sha256: str = ""
    content_type: str = ""


@dataclass(frozen=True)
class ArtifactMeta:
    ref: ArtifactRef
    created_at: float = 0.0
    expires_at: float | None = None


@dataclass
class StreamState:
    """流式护栏的累积态（可变的契约类型）。"""

    buffer: str = ""
    blocks: int = 0
    resumed: bool = False


@dataclass(frozen=True)
class Effect:
    """`dry_run` 的产物：效果即数据（SPEC M1.10）。"""

    kind: Literal["model", "tool"] = "tool"
    step: Step | None = None
    spec: ToolSpec | None = None
    est_tokens: int = 0


@dataclass(frozen=True)
class LayerSpec:
    """层的声明形态（可序列化）；`Layer` 的运行形态含闭包，不可序列化。"""

    name: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProgramSpec:
    body: str = "react"
    max_steps: int = 24
    workflow: tuple[dict[str, Any], ...] = ()
    layers: tuple[LayerSpec, ...] = ()


# ------------------------------------------------------------------ 拓扑


@dataclass(frozen=True)
class Route:
    name: str
    accepts: list[str] = field(default_factory=list)
    fallback: bool = False


@dataclass
class Board:
    state: "State"
    rev: int = 0
    owner: str | None = None


# ------------------------------------------------------------------ 运行时上下文（v1 兼容）


@dataclass
class RunContext:
    """v1 服务定位器，保留兼容；v2 用 `kernel.scope.RunScope`。"""

    state: "State"
    actor: Any
    context: Any
    budget: Any
    tracer: Any
    knowledge: Any = None
    memory: Any = None
    skills: Any = None
    config: Any = None


# ------------------------------------------------------------------ 层请求/响应（SPEC M1.7）


@dataclass(frozen=True)
class RunRequest:
    goal: Goal
    ns: Namespace = field(default_factory=Namespace)
    state: Any = None


@dataclass(frozen=True)
class StepRequest:
    state: "State"
    step: Step | Done


@dataclass(frozen=True)
class ModelRequest:
    state: Any = None
    messages: tuple[Message, ...] = ()
    tools: tuple[dict[str, Any], ...] = ()
    budget: Budget | None = None
    frame: Frame | None = None


@dataclass(frozen=True)
class ToolRequest:
    step: Step
    spec: ToolSpec | None = None


@dataclass(frozen=True)
class RunResponse:
    result: Any = None


@dataclass(frozen=True)
class StepResponse:
    step: Step | None = None


@dataclass(frozen=True)
class ModelResponse:
    reply: ModelReply | None = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResponse:
    result: ToolResult | None = None


Request = RunRequest | StepRequest | ModelRequest | ToolRequest
Response = RunResponse | StepResponse | ModelResponse | ToolResponse

__all__ = [
    # 标识
    "Namespace", "SessionRef", "SessionMeta", "RunId", "TraceId",
    # 输入
    "Goal", "Brief", "TaskSpec",
    # 过程
    "Step", "ToolCall", "Done", "Plan", "ModelReply", "ModelDelta", "ResponseFormat", "Message",
    # 判定
    "Verdict", "GuardDecision", "Content", "GuardrailVerdict", "Decision", "Failure",
    # 结果
    "ActionResult", "ToolResult", "ExecResult", "Pack", "Recalled",
    # 视图
    "Section", "Frame", "Card",
    # 治理
    "Budget", "Limits", "Mount", "ApprovalRequest", "Checkpoint", "Recorded", "Page",
    # 工具
    "ToolSpec", "ToolContext",
    # 后端数据
    "Document", "Job", "Match", "Stat", "ArtifactRef", "ArtifactMeta", "StreamState",
    "Effect", "LayerSpec", "ProgramSpec",
    # 拓扑
    "Route", "Board",
    # v1 兼容
    "RunContext",
    # 层机制
    "RunRequest", "StepRequest", "ModelRequest", "ToolRequest",
    "RunResponse", "StepResponse", "ModelResponse", "ToolResponse",
    "Request", "Response", "Handler",
    # 枚举
    "RunStatus", "TERMINAL_STATUSES", "Phase", "Point", "FrameKind", "Gate5",
    "SideEffect", "GuardAction", "GuardrailAction",
    # 事件
    "TraceEvent", "RunEvent", "HookEvent", "Span", "EVENT_NAMES",
]
