"""Resilience：包住一次模型/工具调用，而不是整个循环。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass
class Resilience:
    timeout_s: float = 30.0
    retries: int = 0
    backoff_s: float = 0.0

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return await asyncio.wait_for(fn(), timeout=self.timeout_s)
            except Exception as exc:  # noqa: BLE001 - 统一重试边界
                last = exc
                if attempt >= self.retries:
                    raise
                if self.backoff_s:
                    await asyncio.sleep(self.backoff_s * (attempt + 1))
        raise last  # pragma: no cover
