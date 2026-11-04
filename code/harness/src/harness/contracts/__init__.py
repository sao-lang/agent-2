"""L1 契约层：类型、协议、错误、结果。零依赖（仅标准库）。"""

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
from harness.contracts import types as _types
from harness.contracts.types import *  # noqa: F403

contracts_version = "2"

__all__ = [
    *(n for n in dir(_types) if not n.startswith("_")),
    "State",
    "RunResult",
    "HarnessError",
    "ConfigError",
    "BudgetExceeded",
    "GuardDenied",
    "ToolError",
    "ReflectorReject",
    "ApprovalExpired",
    "MaxStepsExceeded",
    "ContractError",
    "contracts_version",
]
