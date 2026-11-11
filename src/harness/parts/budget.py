"""预算（转发壳，P1 合并 §4.3.1）：唯一实现在 :mod:`harness.contracts.types`。

历史上 v1 线用本模块的 60k/30 小 Budget，v2/v3 线用 contracts 的
200k/60 Budget（带 split/view/owner）——同名两份实现已在 P1 统一：
顶层与装配层全部改指 ``contracts.types.Budget``，``NullBudget`` 一并
迁入契约层。本模块只为旧导入路径保留转发。
"""

from harness.contracts.types import Budget, NullBudget

__all__ = ["Budget", "NullBudget"]
