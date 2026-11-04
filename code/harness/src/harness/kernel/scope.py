"""L0 内核：运行作用域。

作用域只持有**不可变的能力引用**；可变状态只有 `State`（见 SPEC M2.4）。
子 agent 通过 `child()` 派生：新命名空间、切分预算、独立沙箱、span 挂父。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from harness.contracts.types import Namespace  # noqa: F401  （复用契约层的四段元组）


@dataclass(frozen=True)
class RunScope:
    """一次运行期间的只读能力集合。

    P1 只落地与内核四段链直��相关的字段；存储/后端在 P3 接入时补齐，
    但**新增字段必须有默认值**（契约只增不改，见 SPEC M1.1 纪律 4）。
    """

    namespace: Namespace = field(default_factory=Namespace)
    budget: Any = None
    tracer: Any = None
    delivery: Any = None
    guard: Any = None
    pipes: tuple[Any, ...] = ()
    layers: tuple[Any, ...] = ()
    filter: Any = None
    clock: Any = None
    config: Any = None
    depth: int = 0
    max_depth: int = 2
    #: 子 agent 并发槽位。挂在这里而不是挂在层上：层是值、会被复制，
    #: 挂在层上会导致"每层各造一个信号量"，总量失控（SPEC M13.7）。
    child_slots: Any = None
    capacity: dict[str, Any] = field(default_factory=dict)

    def child(self, name: str, *, budget_fraction: float = 0.3) -> "RunScope":
        """派生子作用域：实现"资源单一所有者"不变量（单向继承）。"""
        if self.depth + 1 > self.max_depth:
            from harness.contracts.errors import ConfigError

            raise ConfigError(
                f"子 agent 深度超过上限 {self.max_depth}：{self.namespace.agent} -> {name}"
            )
        child_budget = self.budget
        if self.budget is not None and hasattr(self.budget, "split"):
            child_budget = self.budget.split(budget_fraction)
        return replace(
            self,
            namespace=replace(self.namespace, agent=name),
            budget=child_budget,
            depth=self.depth + 1,
        )