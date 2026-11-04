"""L1 契约层：类型、协议、事件、错误、结果。零依赖（仅标准库）。

对外统一从这里再导出；子模块只负责可读性。
"""

from harness.contracts import events as _events
from harness.contracts import protocols as _protocols
from harness.contracts import status as _status
from harness.contracts import types as _types
from harness.contracts.errors import (
    ApprovalExpired,
    BudgetError,
    BudgetExceeded,
    ConcurrencyError,
    ConfigError,
    ContractError,
    GuardDenied,
    HarnessError,
    MaxStepsExceeded,
    PolicyError,
    ReflectorReject,
    ToolError,
    TransientError,
    ValidationError,
)
from harness.contracts.events import *  # noqa: F401,F403
from harness.contracts.protocols import *  # noqa: F401,F403
from harness.contracts.result import RunResult
from harness.contracts.state import State
from harness.contracts.status import *  # noqa: F401,F403
from harness.contracts.types import *  # noqa: F401,F403

contracts_version = "2"

_ERRORS = [
    "HarnessError",
    "ConfigError",
    "BudgetExceeded",
    "BudgetError",
    "GuardDenied",
    "ToolError",
    "ReflectorReject",
    "ApprovalExpired",
    "MaxStepsExceeded",
    "ContractError",
    "ValidationError",
    "ConcurrencyError",
    "TransientError",
    "PolicyError",
]

__all__ = sorted(
    {
        *_types.__all__,
        *_protocols.__all__,
        *_status.__all__,
        *_events.__all__,
        "State",
        "RunResult",
        "contracts_version",
        *_ERRORS,
    }
)
