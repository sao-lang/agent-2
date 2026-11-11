"""预算（转发壳，P1 合并 §4.3.1）：唯一实现在 :mod:`harness.contracts.types`。

同名两份实现已在 P1 统一：顶层与装配层全部改指
``contracts.types.Budget``（带 split/view/owner），``NullBudget`` 一并
迁入契约层。本模块只为旧导入路径保留转发。
"""

from harness.contracts.types import Budget, NullBudget

__all__ = ["Budget", "NullBudget"]
