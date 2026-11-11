"""Resilience：包住一次模型/工具调用，而不是整个循环。

三个维度（C03 补全）：
    1 超时 + 重试 + 退避：``timeout_s / retries / backoff_s``
    2 限流：``max_qps``（滑动窗口；0 = 不限流）
    3 熔断：``CircuitBreaker``（closed → open → half_open）
全部只在显式装配（``LlmActor.resilience``）时启用，默认 None 不行为。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class CircuitOpen(Exception):
    """熔断打开期间的调用被快速拒绝，不打到下游。"""


class CircuitBreaker:
    """三态熔断器：连续失败达到阈值 → 打开；冷却后半开试探。"""

    def __init__(self, *, failure_threshold: int = 5, recovery_s: float = 30.0,
                 half_open_max: int = 1) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_s = max(0.0, recovery_s)
        self.half_open_max = max(1, half_open_max)
        self.state: str = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.half_open_inflight = 0

    def allow(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.monotonic() - self.opened_at >= self.recovery_s:
                self.state = "half_open"
                self.half_open_inflight = 0
            else:
                return False
        # half_open：只放行试探配额内的调用
        if self.half_open_inflight >= self.half_open_max:
            return False
        self.half_open_inflight += 1
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.half_open_inflight = 0
        self.state = "closed"

    def record_failure(self) -> None:
        if self.state == "half_open":
            # 试探失败：重新打开，重新计时
            self.state = "open"
            self.opened_at = time.monotonic()
            self.half_open_inflight = 0
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.monotonic()


@dataclass
class Resilience:
    timeout_s: float = 30.0
    retries: int = 0
    backoff_s: float = 0.0
    max_qps: float = 0.0                       # 0 = 不限流
    breaker: CircuitBreaker | None = None
    _call_times: list[float] = field(default_factory=list, repr=False,
                                     compare=False)

    def _throttle(self) -> None:
        """滑动窗口限流：超过 max_qps 时等到窗口滑出最早的调用。"""
        if self.max_qps <= 0:
            return
        now = time.monotonic()
        window = 1.0
        self._call_times = [t for t in self._call_times if now - t < window]
        if len(self._call_times) >= self.max_qps:
            wait = window - (now - self._call_times[0])
            if wait > 0:
                time.sleep(wait)               # 同步等待：调用频率天然不高
            now = time.monotonic()
            self._call_times = [t for t in self._call_times if now - t < window]
        self._call_times.append(now)

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self.breaker is not None and not self.breaker.allow():
            raise CircuitOpen("熔断打开：快速失败（fail-fast）")
        self._throttle()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                out = await asyncio.wait_for(fn(), timeout=self.timeout_s)
            except Exception as exc:  # noqa: BLE001 - 统一重试边界
                last = exc
                if self.breaker is not None:
                    self.breaker.record_failure()
                if attempt >= self.retries:
                    raise
                if self.backoff_s:
                    await asyncio.sleep(self.backoff_s * (attempt + 1))
            else:
                if self.breaker is not None:
                    self.breaker.record_success()
                return out
        raise last  # pragma: no cover
