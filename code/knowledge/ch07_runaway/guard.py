"""循环守卫：四种失控各自的判定，与"结果指纹"。

不联网。守卫只看每步的 (prompt_tokens, 调用指纹, 结果指纹, 回灌长度)，
用来演示四种信号分别长什么样。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class Step:
    prompt_tokens: int
    call_fp: str
    result_fp: str
    payload_chars: int
    empty: bool


@dataclass
class Guard:
    max_steps: int = 8
    max_prompt_tokens: int = 6000
    max_total_tokens: int = 30000
    max_same_result: int = 2
    max_empty_streak: int = 2

    total_tokens: int = 0
    seen_calls: dict[str, int] = field(default_factory=dict)
    seen_results: dict[str, int] = field(default_factory=dict)
    empty_streak: int = 0

    def check(self, step: Step) -> str | None:
        """返回 None 表示继续，否则返回停下来的原因。"""
        self.total_tokens += step.prompt_tokens
        self.seen_calls[step.call_fp] = self.seen_calls.get(step.call_fp, 0) + 1
        self.seen_results[step.result_fp] = self.seen_results.get(step.result_fp, 0) + 1
        self.empty_streak = self.empty_streak + 1 if step.empty else 0

        if self.seen_calls[step.call_fp] > 1:
            return "重复调用（同一请求指纹）"
        if self.seen_results[step.result_fp] > self.max_same_result:
            return "换参数打转（同一结果指纹）"
        if self.empty_streak >= self.max_empty_streak:
            return f"连续 {self.empty_streak} 步空回灌"
        if step.prompt_tokens > self.max_prompt_tokens:
            return f"单步 prompt 超限（{step.prompt_tokens}）"
        if self.total_tokens > self.max_total_tokens:
            return f"累计 token 超限（{self.total_tokens}）"
        return None

    def step_by_step(self, steps: list[Step]) -> tuple[str, int]:
        for i, s in enumerate(steps, 1):
            reason = self.check(s)
            if reason:
                return reason, i
            if i >= self.max_steps:
                return "步数上限", i
        return "脚本用尽", len(steps)


def result_fp(content: str) -> str:
    """结果指纹：对回灌内容做规范化哈希。同样的数据，不同措辞也算不同。"""
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    cases = {
        "重复调用": [
            Step(1000 + i * 100, "get_logs::api", result_fp("same"), 500, False)
            for i in range(5)
        ],
        "换参数打转": [
            Step(1000 + i * 100, f"get_logs::svc{i}", result_fp("same"), 500, False)
            for i in range(5)
        ],
        "连续空回灌": [
            Step(1000 + i * 100, f"get_logs::svc{i}", result_fp(f"e{i}"), 30, True)
            for i in range(5)
        ],
        "上下文爆炸": [
            Step(1000 + i * 2500, f"get_logs::svc{i}", result_fp(f"r{i}"), 9000, False)
            for i in range(5)
        ],
    }
    for name, steps in cases.items():
        reason, n = Guard().step_by_step(steps)
        print(f"{name:<10} -> 第 {n} 步停：{reason}")


if __name__ == "__main__":
    main()
