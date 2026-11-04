"""基座异常。调用方按类型区分失败，不要一律 except Exception。"""

from __future__ import annotations


class HarnessError(Exception):
    """所有基座异常的根。"""


class ConfigError(HarnessError):
    """配置组合非法，例如 mode=workflow 却传了 planner。"""


class BudgetExceeded(HarnessError):
    pass


class GuardDenied(HarnessError):
    pass


class ToolError(HarnessError):
    pass


class ReflectorReject(HarnessError):
    pass


class ApprovalExpired(HarnessError):
    pass


class MaxStepsExceeded(HarnessError):
    pass


class ContractError(HarnessError):
    """组件返回的类型不符合契约。"""
