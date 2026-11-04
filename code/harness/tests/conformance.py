"""一致性测试基类（SPEC M16.3）。

任何存储实现继承这些基类、只提供 `factory()`；**通过即可替换**。
子类不得跳过用例。
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime

from harness.contracts.errors import ConcurrencyError
from harness.contracts.state import State
from harness.contracts.types import Goal, Namespace, Recalled, SessionRef


def _state(text: str = "t") -> State:
    return State(goal=Goal(text, session_id="s1"), session=SessionRef("s1"))


def session_ref(sid: str = "s1") -> SessionRef:
    return SessionRef(sid)


NS_A = Namespace(tenant="t1", user="u1", session="s1", agent="a")
NS_B = Namespace(tenant="t2", user="u2", session="s2", agent="a")


class CheckpointStoreConformance:
    """C1 历史不可变 + C2 乐观并发 + C3 命名空间隔离。"""

    def factory(self):  # pragma: no cover - 子类实现
        raise NotImplementedError

    def setUp(self) -> None:
        self.store = self.factory()

    def run_(self, coro):
        return asyncio.run(coro)

    def test_put_get_roundtrip(self):
        state = _state("hello")
        rev = self.run_(self.store.put(NS_A, "s1", state, expect_rev=None))
        self.assertEqual(rev, 0)
        got = self.run_(self.store.get(NS_A, "s1"))
        self.assertIsNotNone(got)
        self.assertEqual(got.state.goal.text, "hello")
        self.assertEqual(got.rev, 0)

    def test_history_increasing_rev(self):
        for i in range(3):
            self.run_(self.store.put(NS_A, "s1", _state(f"v{i}"), expect_rev=None))
        self.assertEqual(self.run_(self.store.history(NS_A, "s1")), [0, 1, 2])

    def test_old_rev_immutable(self):
        self.run_(self.store.put(NS_A, "s1", _state("v0"), expect_rev=None))
        self.run_(self.store.put(NS_A, "s1", _state("v1"), expect_rev=None))
        first = self.run_(self.store.get(NS_A, "s1", 0))
        self.assertEqual(first.state.goal.text, "v0")   # C1

    def test_optimistic_conflict_raises(self):
        self.run_(self.store.put(NS_A, "s1", _state("v0"), expect_rev=None))
        with self.assertRaises(ConcurrencyError):
            self.run_(self.store.put(NS_A, "s1", _state("v1"), expect_rev=5))

    def test_namespace_isolation(self):
        self.run_(self.store.put(NS_A, "s1", _state("secret"), expect_rev=None))
        self.assertIsNone(self.run_(self.store.get(NS_B, "s1")))


class MessageLogConformance:
    """C5 append-only + C6 尾读预算 + C3 隔离。"""

    def factory(self):  # pragma: no cover
        raise NotImplementedError

    def setUp(self) -> None:
        self.log = self.factory()

    def run_(self, coro):
        return asyncio.run(coro)

    def test_append_only(self):
        self.run_(self.log.append(NS_A, "s1", [{"role": "user", "content": "a"}]))
        self.run_(self.log.append(NS_A, "s1", [{"role": "assistant", "content": "b"}]))
        tail = self.run_(self.log.tail(NS_A, "s1", max_tokens=100))
        self.assertEqual([m["content"] for m in tail], ["a", "b"])

    def test_tail_respects_token_budget(self):
        for i in range(20):
            self.run_(self.log.append(NS_A, "s1", [{"role": "user", "content": "x" * 400}]))
        tail = self.run_(self.log.tail(NS_A, "s1", max_tokens=50))   # ≈200 字符
        self.assertLess(len(tail), 20)
        self.assertGreaterEqual(len(tail), 1)

    def test_namespace_isolation(self):
        self.run_(self.log.append(NS_B, "s1", [{"role": "user", "content": "other"}]))
        self.assertEqual(self.run_(self.log.tail(NS_A, "s1", max_tokens=100)), [])


class IdempotencyConformance:
    """C7 点查命中。"""

    def factory(self):  # pragma: no cover
        raise NotImplementedError

    def setUp(self) -> None:
        self.store = self.factory()

    def run_(self, coro):
        return asyncio.run(coro)

    def test_miss_then_hit(self):
        from harness.contracts.types import Recorded

        self.assertIsNone(self.run_(self.store.begin(NS_A, "k1")))
        self.run_(self.store.commit(NS_A, "k1", Recorded("k1", "value")))
        hit = self.run_(self.store.begin(NS_A, "k1"))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, "value")

    def test_namespace_isolation(self):
        from harness.contracts.types import Recorded

        self.run_(self.store.commit(NS_A, "k1", Recorded("k1", "v")))
        self.assertIsNone(self.run_(self.store.begin(NS_B, "k1")))


class MemoryStoreConformance:
    """C3 隔离 + C4 去重 + 软删 + 过期。"""

    def factory(self):  # pragma: no cover
        raise NotImplementedError

    def setUp(self) -> None:
        self.store = self.factory()

    def run_(self, coro):
        return asyncio.run(coro)

    def test_upsert_then_recall(self):
        self.run_(self.store.upsert(NS_A, [Recalled(text="a", dedup_key="d1", id="1")]))
        self.assertEqual(len(self.run_(self.store.recall(NS_A, "a", k=5))), 1)

    def test_recall_limits_k_and_orders_by_score(self):
        items = [Recalled(text=f"i{i}", score=i / 10, dedup_key=f"d{i}") for i in range(5)]
        self.run_(self.store.upsert(NS_A, items))
        got = self.run_(self.store.recall(NS_A, "i", k=3))
        self.assertEqual(len(got), 3)
        self.assertEqual([r.score for r in got], sorted([r.score for r in got], reverse=True))

    def test_namespace_isolation(self):
        self.run_(self.store.upsert(NS_B, [Recalled(text="x", dedup_key="d1")]))
        self.assertEqual(self.run_(self.store.recall(NS_A, "x", k=5)), [])

    def test_dedup_key_overwrites_not_appends(self):
        self.run_(self.store.upsert(NS_A, [Recalled(text="v1", dedup_key="d1", id="1")]))
        self.run_(self.store.upsert(NS_A, [Recalled(text="v2", dedup_key="d1", id="2")]))
        got = self.run_(self.store.recall(NS_A, "v", k=10))
        self.assertEqual(len(got), 1)          # 当前版本只有一条
        self.assertEqual(got[0].text, "v2")
        self.assertEqual(got[0].superseded_by, "")
        rows = self.run_(self.store.all_items(NS_A)) if hasattr(self.store, "all_items") else []
        if rows:                                # 旧值保留为超链接（可选能力）
            self.assertEqual(len(rows), 2)
            self.assertTrue(any(r.superseded_by for r in rows))

    def test_forget_is_soft_and_hides_from_recall(self):
        self.run_(self.store.upsert(NS_A, [Recalled(text="gone", dedup_key="d1", id="1")]))
        self.run_(self.store.forget(NS_A, ["1"]))
        self.assertEqual(self.run_(self.store.recall(NS_A, "gone", k=5)), [])

    def test_expire_removes_from_recall(self):
        self.run_(
            self.store.upsert(
                NS_A, [Recalled(text="old", dedup_key="d1", id="1", age_days=10_000)]
            )
        )
        self.run_(self.store.expire(NS_A, datetime(2026, 1, 1)))
        self.assertEqual(self.run_(self.store.recall(NS_A, "old", k=5)), [])


class SessionStoreConformance:
    """C3 隔离 + 分页 + 更新。"""

    def factory(self):  # pragma: no cover
        raise NotImplementedError

    def setUp(self) -> None:
        self.store = self.factory()

    def run_(self, coro):
        return asyncio.run(coro)

    def test_create_get_update(self):
        from harness.contracts.types import SessionMeta

        self.run_(self.store.create(NS_A, SessionMeta(id="s1", title="t")))
        self.assertEqual(self.run_(self.store.get(NS_A, "s1")).title, "t")
        self.run_(self.store.update(NS_A, "s1", {"title": "t2"}))
        self.assertEqual(self.run_(self.store.get(NS_A, "s1")).title, "t2")

    def test_list_paginates(self):
        from harness.contracts.types import SessionMeta

        for i in range(5):
            self.run_(self.store.create(NS_A, SessionMeta(id=f"s{i}")))
        page = self.run_(self.store.list(NS_A, limit=2))
        self.assertEqual(len(page.items), 2)
        self.assertIsNotNone(page.cursor)

    def test_namespace_isolation(self):
        from harness.contracts.types import SessionMeta

        self.run_(self.store.create(NS_B, SessionMeta(id="s1")))
        self.assertIsNone(self.run_(self.store.get(NS_A, "s1")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
