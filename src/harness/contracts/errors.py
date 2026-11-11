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


# ---- SPEC M16.1.1 的错误分类（P1 先落类型，映射在 kernel.stage.DefaultClassify）


class ValidationError(HarnessError):
    """参数不合法（Check 段的产物）。携带字段路径，便于模型自愈。"""

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(f"{field}: {message}" if field else message)
        self.field = field


class ConcurrencyError(HarnessError):
    """乐观并发冲突（expect_rev 不匹配）。"""


class TransientError(HarnessError):
    """可重试失败：超时、限流、5xx。"""


class PolicyError(HarnessError):
    """准入或护栏拒绝。"""


# ---- 通用解释器（PROPOSAL §9.2）----


class DecisionError(ContractError):
    """``transition`` 返回了不符合契约的东西。"""


class EffectError(HarnessError):
    """效应请求无法执行（未注册 kind、参数缺失等）。"""


class NotSerializable(ConfigError, TypeError):
    """闭包程序/层不提供 ``to_spec()``：显式降级，不假装可序列化。

    同时继承 ``TypeError`` 以兼容「to_spec 抛 NotSerializable」的旧调用点。
    """


#: SPEC 里叫 BudgetError；保留旧名以兼容既有代码。
BudgetError = BudgetExceeded

__all__ = [
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
    "DecisionError",
    "EffectError",
    "NotSerializable",
]
