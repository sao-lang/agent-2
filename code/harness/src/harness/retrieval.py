"""RetrievalPolicy：什么时候取、拿什么 query 去取。"""

from __future__ import annotations

from .contracts import Goal, Recalled
from .knowledge import InMemoryKnowledge


class AutoRetrieval:
    def __init__(self, k: int = 6, when: str = "first_step") -> None:
        self.k = k
        self.when = when

    async def retrieve(self, goal: Goal, knowledge: InMemoryKnowledge,
                       tenant: str = "default") -> list[Recalled]:
        return await knowledge.retrieve(
            goal.text, k=self.k, filters={"tenant": tenant} if tenant else None
        )


class NoRetrieval:
    async def retrieve(self, goal: Goal, knowledge, tenant: str = "default") -> list[Recalled]:
        return []
