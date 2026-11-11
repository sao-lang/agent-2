"""层机制（SPEC M13.1）：可组合的包裹单元。

层是**值**：`Layer` 只装声明与一个纯函数 `build(handler) -> handler`。
状态放在闭包里或作用域里，不放在层实例上——否则层无法复用与比较。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

Handler = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True)
class Layer:
    """一个可组合的程序片。

    - `points`：在哪些插点生效
    - `needs`：依赖哪些能力（缺则在装配期报错，不降级）
    - `after`/`before`：相对顺序声明，由 `kernel.chain.resolve` 拓扑排序
    - `build`：纯函数，把内层 handler 包成新的 handler
    """

    name: str
    points: frozenset[str]
    build: Callable[[Handler], Handler] = field(compare=False, repr=False)
    needs: frozenset[str] = frozenset()
    after: frozenset[str] = frozenset()
    before: frozenset[str] = frozenset()

    def wrap(self, nxt: Handler) -> Handler:
        return self.build(nxt)


def layer(
    name: str,
    points: Iterable[str],
    build: Callable[[Handler], Handler],
    *,
    needs: Iterable[str] = (),
    after: Iterable[str] = (),
    before: Iterable[str] = (),
) -> Layer:
    """构造一个层（语法糖，避免到处写 frozenset）。"""
    return Layer(
        name=name,
        points=frozenset(points),
        build=build,
        needs=frozenset(needs),
        after=frozenset(after),
        before=frozenset(before),
    )


def compose_layers(*layers: Layer) -> list[Layer]:
    """只做保留顺序的扁平化；真正的排序交给 `kernel.chain.resolve`。"""
    return list(layers)


__all__ = ["Handler", "Layer", "layer", "compose_layers"]
