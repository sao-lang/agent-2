"""L0 内核：链执行器（拓扑排序 + 洋葱）。

只对**同一插点**内的层排序；环 → ConfigError；洋葱只在 Wrap 段使用。
"""

from __future__ import annotations

from typing import Any, Sequence

from harness.contracts.errors import ConfigError

POINTS = ("run", "step", "model_call", "tool_call")


def _points_of(layer: Any) -> frozenset[str]:
    raw = getattr(layer, "points", frozenset())
    if isinstance(raw, str):
        raw = {raw}
    return frozenset(raw)


def resolve(layers: Sequence[Any], point: str) -> list[Any]:
    """筛出该插点的层并按 after/before 拓扑排序。

    无约束的层保持注册顺序（稳定排序），保证可复现。
    """
    if point not in POINTS:
        raise ConfigError(f"未知插点：{point!r}，合法值 {POINTS}")

    picked = [lay for lay in layers if point in _points_of(lay)]
    names = [getattr(lay, "name", f"layer{i}") for i, lay in enumerate(picked)]
    if len(set(names)) != len(names):
        raise ConfigError(f"插点 {point} 上存在重名层：{names}")

    edges: dict[str, set[str]] = {n: set() for n in names}
    for lay, name in zip(picked, names):
        for dep in getattr(lay, "after", frozenset()):
            if dep in edges:
                edges[name].add(dep)
        for dep in getattr(lay, "before", frozenset()):
            if dep in edges:
                edges[dep].add(name)

    ordered: list[str] = []
    pending: dict[str, set[str]] = {n: set(d) for n, d in edges.items()}
    while pending:
        ready = [n for n in names if n in pending and not pending[n]]
        if not ready:
            raise ConfigError(f"插点 {point} 的层顺序成环：{sorted(pending)}")
        for n in ready:
            ordered.append(n)
            del pending[n]
        for deps in pending.values():
            deps.difference_update(ready)

    by_name = dict(zip(names, picked))
    return [by_name[n] for n in ordered]


def describe(layers: Sequence[Any], point: str) -> str:
    return " > ".join(getattr(lay, "name", "?") for lay in resolve(layers, point))


async def execute(layers: Sequence[Any], request: Any, terminal: Any) -> Any:
    """洋葱执行：第一层最外，最后一层最内，逐层包裹终端。

    层可以是 `Layer`（有 `wrap`）或普通 `(req, nxt)` 可调用对象。
    """

    def _wrap(lay: Any, nxt: Any) -> Any:
        if hasattr(lay, "wrap"):
            return lay.wrap(nxt)

        async def call(req: Any, *, _lay=lay, _nxt=nxt) -> Any:
            return await _lay(req, _nxt)

        return call

    handler = terminal
    for lay in reversed(list(layers)):
        handler = _wrap(lay, handler)
    return await handler(request)
