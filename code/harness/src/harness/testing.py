"""兼容壳：`harness.testing` 已迁至 `harness.impl.fakes`。"""

from harness.impl.fakes import FakeModel, answer, tool_call  # noqa: F401

__all__ = ["FakeModel", "answer", "tool_call"]
