"""枚举与状态机（SPEC M1.2、M16.2）。零依赖。"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """运行终态的七种取值（SPEC M16.2）。

    `RUNNING` 只存在于内存态，**禁止出现在 `RunResult`**。
    """

    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    REFUSED = "refused"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(RunStatus) - {RunStatus.RUNNING}


class Phase(StrEnum):
    """失败发生在哪一段（供 `Filter.classify` 使用）。"""

    RUN = "run"
    STEP = "step"
    GATE = "gate"
    CHECK = "check"
    WRAP = "wrap"
    CLASSIFY = "classify"
    MODEL = "model"
    TOOL = "tool"
    EXPORT = "export"


class Point(StrEnum):
    """四个可包裹插点（SPEC M2.3）。"""

    RUN = "run"
    STEP = "step"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"


class FrameKind(StrEnum):
    """四种帧（SPEC M6.1）。"""

    MODEL = "model"
    HUMAN = "human"
    APPROVAL = "approval"
    TRACE = "trace"


class Gate5(StrEnum):
    """护栏五道闸（SPEC M9.1）。"""

    INBOUND = "inbound"
    CONTEXT = "context"
    MODEL_OUT = "model_out"
    TOOL_OUT = "tool_out"
    OUTBOUND = "outbound"


class SideEffect(StrEnum):
    """工具副作用等级，驱动审批分级、幂等要求、沙箱路由（SPEC M3.5）。"""

    PURE = "pure"
    READ = "read"
    WRITE = "write"
    NET = "net"
    SHELL = "shell"


class GuardAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class GuardrailAction(StrEnum):
    """动作强度递增，仲裁取最严（SPEC M9.3）。"""

    ALLOW = "allow"
    WARN = "warn"
    REDACT = "redact"
    REWRITE = "rewrite"
    ASK = "ask"
    BLOCK = "block"


__all__ = [
    "RunStatus",
    "TERMINAL_STATUSES",
    "Phase",
    "Point",
    "FrameKind",
    "Gate5",
    "SideEffect",
    "GuardAction",
    "GuardrailAction",
]
