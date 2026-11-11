"""预算：token 与调用次数。预算是共享资源，不是某个组件的私有财产。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Budget:
    tokens: int = 60_000
    calls: int = 30
    used_tokens: int = 0
    used_calls: int = 0

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.tokens - self.used_tokens)

    @property
    def remaining_calls(self) -> int:
        return max(0, self.calls - self.used_calls)

    @property
    def exhausted(self) -> bool:
        return self.remaining_tokens <= 0 or self.remaining_calls <= 0

    def spend(self, tokens: int = 0, calls: int = 1) -> None:
        self.used_tokens += max(0, tokens)
        self.used_calls += max(0, calls)

    def snapshot(self) -> dict[str, int]:
        return {
            "tokens": self.tokens,
            "calls": self.calls,
            "used_tokens": self.used_tokens,
            "used_calls": self.used_calls,
        }


class NullBudget(Budget):
    """测试用：永不耗尽。"""

    def __init__(self) -> None:
        super().__init__(tokens=10**12, calls=10**9)
