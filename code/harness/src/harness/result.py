"""兼容壳：`harness.result` 已迁至 `harness.contracts.result`。"""

from harness.contracts.result import RunResult  # noqa: F401

__all__ = ["RunResult"]
