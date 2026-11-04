"""兼容壳：`harness.state` 已迁至 `harness.contracts.state`。"""

from harness.contracts.state import State  # noqa: F401

__all__ = ["State"]
