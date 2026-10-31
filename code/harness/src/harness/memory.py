"""Memory：跨会话的长期数据；不负责一次运行的检查点。"""

from __future__ import annotations

from .contracts import Recalled
from .knowledge import _score


class InMemoryMemory:
    def __init__(self, items: list[Recalled] | None = None) -> None:
        self.items = list(items or [])

    async def recall(self, query: str, *, scope: str,
                     layers: list[str], k: int) -> list[Recalled]:
        rows = [item for item in self.items if item.layer in layers]
        scored = [(_score(query, item.text), item) for item in rows]
        scored = [pair for pair in scored if pair[0] > 0]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:k]]

    async def write(self, items: list[Recalled]) -> int:
        self.items.extend(items)
        return len(items)
