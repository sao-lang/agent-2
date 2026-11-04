"""存储实现的一致性测试（P3 验收）。

每个实现只提供 factory()，其余用例全部继承——**通过即可替换**（SPEC M16.3）。
"""

from __future__ import annotations

import unittest

from conformance import (
    CheckpointStoreConformance,
    IdempotencyConformance,
    MemoryStoreConformance,
    MessageLogConformance,
    SessionStoreConformance,
)
from harness.impl.stores import (
    ConservativeMemoryPolicy,
    MemoryCheckpointStore,
    MemoryIdempotency,
    MemoryMemoryStore,
    MemoryMessageLog,
    MemorySessionStore,
)


class TestMemoryCheckpointStore(CheckpointStoreConformance, unittest.TestCase):
    def factory(self):
        return MemoryCheckpointStore()


class TestMemoryMessageLog(MessageLogConformance, unittest.TestCase):
    def factory(self):
        return MemoryMessageLog()


class TestMemoryIdempotency(IdempotencyConformance, unittest.TestCase):
    def factory(self):
        return MemoryIdempotency()


class TestMemoryMemoryStore(MemoryStoreConformance, unittest.TestCase):
    def factory(self):
        return MemoryMemoryStore(ttl_days=365)


class TestMemorySessionStore(SessionStoreConformance, unittest.TestCase):
    def factory(self):
        return MemorySessionStore()


class PolicyTest(unittest.TestCase):
    def test_extract_requires_source(self):
        import asyncio

        from harness.contracts.state import State
        from harness.contracts.types import Goal, SessionRef

        policy = ConservativeMemoryPolicy()
        empty = State(goal=Goal("t"), session=SessionRef("s"))
        self.assertEqual(asyncio.run(policy.extract(empty)), [])

        filled = State(goal=Goal("t"), session=SessionRef("s"))
        filled.data["last_output"] = "结论：A1001 已签收"
        items = asyncio.run(policy.extract(filled))
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].source.startswith("run:"))   # 无来源不写

    def test_merge_prefers_new(self):
        import asyncio

        from harness.contracts.types import Recalled

        policy = ConservativeMemoryPolicy()
        merged = asyncio.run(
            policy.merge(
                [Recalled(text="old", dedup_key="d1")],
                [Recalled(text="new", dedup_key="d1")],
            )
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "new")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
