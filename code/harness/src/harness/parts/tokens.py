"""Token 计数器（SUPPLEMENT A6 / 推导 §5.5 约束 5）。

framing 层原按字符估算（1 token ≈ 4 字符），账不可信。这里把计数器抽象成
协议，装配期注入：

* `CharEstimator` —— 零依赖默认实现，与旧 `est_tokens` 完全同口径；
  离线测试与相对比较用它（R6：每个真实现必须配 fake）。
* `TiktokenCounter` —— 真实现（extra：`pip install agent-harness[tiktoken]`）；
  未安装时显式报错，不静默降级。

替换实验：`CharEstimator ↔ TiktokenCounter` 互换，取景/编码行为一致，
只有计数精度变化。
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class TokenCounter(Protocol):
    """计数协议：单段文本 + 一组消息两种口径。"""

    name: str

    def count(self, text: str) -> int: ...

    def count_messages(self, messages: Sequence[dict[str, Any]]) -> int: ...


class CharEstimator:
    """字符估算：1 token ≈ 4 字符。与旧 `framing.est_tokens` 同口径（fake）。"""

    name = "char_estimate"

    def count(self, text: str) -> int:
        return max(1, len(text) // 4) if text else 0

    def count_messages(self, messages: Sequence[dict[str, Any]]) -> int:
        total = 0
        for message in messages or ():
            total += self.count(str(message.get("content", "")))
            for call in message.get("tool_calls") or ():
                total += self.count(str(call))
        return total


class TiktokenCounter:
    """真实现：tiktoken 精确计数（openai 系模型）。零第三方依赖纪律的例外
    放在 extras——本模块惰性 import，未安装报 ConfigError 并给出安装命令。"""

    name = "tiktoken"

    def __init__(self, model: str = "gpt-4.1") -> None:
        try:
            import tiktoken  # noqa: F401  第三方依赖，见 pyproject extras
        except ImportError as exc:
            from harness.contracts.errors import ConfigError

            raise ConfigError(
                "tiktoken 计数器需要安装依赖：pip install agent-harness[tiktoken]"
            ) from exc
        try:
            self._enc = tiktoken.encoding_for_model(model)
        except KeyError:
            self._enc = tiktoken.get_encoding("o200k_base")

    def count(self, text: str) -> int:
        return len(self._enc.encode(text or ""))

    def count_messages(self, messages: Sequence[dict[str, Any]]) -> int:
        # 粗口径：逐条 encode 求和（每条消息的 role/结构开销不计，可量化偏差）
        return sum(self.count(str(m.get("content", ""))) for m in messages or ())


def make_counter(precision: str = "chars", *, model: str = "gpt-4.1") -> TokenCounter:
    """装配期便捷入口：precision="chars"（默认，离线）| "tiktoken"（真实现）。"""
    if precision == "tiktoken":
        return TiktokenCounter(model=model)
    if precision == "chars":
        return CharEstimator()
    raise ValueError(f"未知计数精度：{precision!r}（可选 chars / tiktoken）")


__all__ = ["TokenCounter", "CharEstimator", "TiktokenCounter", "make_counter"]
