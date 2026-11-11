"""场景测试：RAG 与记忆（v3 层机制）。"""

from __future__ import annotations

import asyncio
import unittest

from harness import Goal, InMemoryKnowledge, InMemoryMemory, Recalled, RunStatus
from harness.fp import Harness, react
from harness.parts.layers import memory_recall_layer, retrieval_layer
from harness.parts.retrieval import AutoRetrieval, NoRetrieval
from harness.parts.tools import tool
from support import FakeModel, answer, tool_call


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


class TestScenarios(unittest.TestCase):
    def test_rag_context_contains_retrieved(self):
        kb = InMemoryKnowledge([
            Recalled("退货政策：签收后 7 天内未拆封可退", source="tenant=acme"),
            Recalled("物流时效：一般 3 天送达", source="tenant=acme"),
        ])
        model = FakeModel([tool_call("concat", left="a", right="b"), answer("7 天内可退")])
        h = Harness.of(model=model, tools=[concat], system="你是客服")
        # 检索层挂 model_call 插点：候选写进 state.data["retrieved"]，
        # 下一轮取景即进入 system 段（# 资料）。
        program = react(max_steps=4) >> retrieval_layer(knowledge=kb, k=2)
        result = asyncio.run(h.run(program, Goal("退货政策是什么", session_id="s-r")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertTrue(result.state.data.get("retrieved"))
        system = model.seen[1][0]["content"]   # 第二次取景已含第一轮检索结果
        self.assertIn("7 天内未拆封可退", system)
        self.assertIn("资料", system)

    def test_memory_recall(self):
        memory = InMemoryMemory([
            Recalled("用户偏好简体中文", layer="semantic", source="user_preference"),
        ])
        model = FakeModel([tool_call("concat", left="a", right="b"), answer("好的")])
        h = Harness.of(model=model, tools=[concat])
        program = react(max_steps=4) >> memory_recall_layer(
            memory=memory, layers=("semantic",), k=3)
        result = asyncio.run(h.run(program, Goal("用简体中文写一句", user_id="u1",
                                                 session_id="s-m")))
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertTrue(result.state.data.get("memory"))
        system = model.seen[1][0]["content"]
        self.assertIn("用户偏好简体中文", system)
        self.assertIn("记忆", system)

    def test_retrieval_policy_replacement(self):
        """替换实验：AutoRetrieval ↔ NoRetrieval，取与不取只差检索结果。"""
        kb = InMemoryKnowledge([Recalled("退货政策：7 天可退", source="tenant=acme")])
        goal = Goal("退货政策是什么", session_id="r")
        got = asyncio.run(AutoRetrieval(k=2).retrieve(goal, kb, tenant="acme"))
        self.assertEqual([item.text for item in got], ["退货政策：7 天可退"])
        nothing = asyncio.run(NoRetrieval().retrieve(goal, kb))
        self.assertEqual(nothing, [])


if __name__ == "__main__":
    unittest.main()
