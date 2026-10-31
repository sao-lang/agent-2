"""Knowledge：取哪几条。只负责检索，不负责预算与拼装。"""

from __future__ import annotations

from .contracts import Recalled


def _bigrams(text: str) -> set[str]:
    clean = "".join(ch for ch in text.lower() if not ch.isspace())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def _score(query: str, text: str) -> float:
    q = _bigrams(query)
    if not q:
        return 0.0
    return len(q & _bigrams(text)) / len(q)


class InMemoryKnowledge:
    """最小实现：字符二元组重合打分，够离线测试与示例。"""

    def __init__(self, items: list[Recalled] | None = None) -> None:
        self.items = list(items or [])

    async def retrieve(self, query: str, *, k: int,
                       filters: dict | None = None) -> list[Recalled]:
        scored: list[tuple[float, Recalled]] = []
        for item in self.items:
            if filters and any(f"{key}={value}" not in item.source
                               for key, value in filters.items()):
                continue
            score = _score(query, item.text)
            if score > 0:
                scored.append((score, Recalled(
                    text=item.text,
                    layer=item.layer,
                    score=score,
                    source=item.source,
                    age_days=item.age_days,
                )))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:k]]
