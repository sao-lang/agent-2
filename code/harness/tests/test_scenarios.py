"""场景测试：RAG 与记忆。"""

from __future__ import annotations

import asyncio
import unittest

from harness import (
    AgentConfig,
    AutoRetrieval,
    BudgetedContext,
    Goal,
    InMemoryKnowledge,
    InMemoryMemory,
    Recalled,
    RunStatus,
    build,
)
from harness.testing import FakeModel, answer


class TestScenarios(unittest.TestCase):
    def test_rag_context_contains_retrieved(self):
        kb = InMemoryKnowledge([
            Recalled("退货政策：签收后 7 天内未拆封可退", source="tenant=acme"),
            Recalled("物流时效：一般 3 天送达", source="tenant=acme"),
        ])
        model = FakeModel([answer("7 天内可退")])
        agent = build(AgentConfig(
            model=model,
            mode="react",
            knowledge=kb,
            retrieval=AutoRetrieval(k=2),
            context=BudgetedContext(system="你是客服"),
        ))
        result = asyncio.run(agent.run(Goal(
            "退货政策是什么", session_id="s-r", metadata={"tenant": "acme"}
        )))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertTrue(result.state.data.get("retrieved"))
        system = model.seen[0][0]["content"]
        self.assertIn("7 天内未拆封可退", system)
        self.assertIn("资料", system)

    def test_memory_recall(self):
        memory = InMemoryMemory([
            Recalled("用户偏好简体中文", layer="semantic", source="user_preference"),
        ])
        model = FakeModel([answer("好的")])
        agent = build(AgentConfig(
            model=model,
            mode="react",
            memory=memory,
            memory_policy={"layers": ["semantic"], "k": 3},
        ))
        result = asyncio.run(agent.run(Goal(
            "用简体中文写一句", user_id="u1", session_id="s-m"
        )))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertTrue(result.state.data.get("memory"))


if __name__ == "__main__":
    unittest.main()
