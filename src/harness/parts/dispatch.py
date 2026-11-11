"""分派层：请求走哪条路。

（SUPPLEMENT A3）：补齐 DEV-SESSION §2 四层表的另外两路——
``LLMRouter``（小模型意图分类）与 ``VectorRouter``（嵌入检索路由，
依赖 IndexBackend 协议，见 impl/backends/vector.py）。四者同签名
``route(goal) -> Route``，可做替换实验（RuleRouter ↔ VectorRouter
互换，下游行为一致，只有分流质量变化）。两者都带 fallback 兜底率统计。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from harness.contracts.types import Goal, Route


class AlwaysRoute:
    def __init__(self, name: str = "default") -> None:
        self.name = name

    async def route(self, goal: Goal) -> Route:
        return Route(self.name, fallback=True)


@dataclass
class RuleRouter:
    routes: list[Route] = field(default_factory=list)
    default: str = "general"

    async def route(self, goal: Goal) -> Route:
        text = goal.text.lower()
        for route in self.routes:
            if any(word.lower() in text for word in route.accepts):
                return route
        for route in self.routes:
            if route.fallback:
                return route
        return Route(self.default, fallback=True)


@dataclass
class LLMRouter:
    """小模型意图分类：把候选路线列进 prompt，模型回 JSON {"route": name}。

    model 只需实现 Model 协议的 complete()；离线测试注入 FakeModel
    （脚本回放 {"route": …}）。解析失败或未知路线 → fallback 并计数。
    """

    routes: list[Route] = field(default_factory=list)
    model: Any = None
    default: str = "general"
    fallback_count: int = 0
    total_count: int = 0

    def _prompt(self, goal: Goal) -> str:
        lines = [f"- {r.name}（关键词：{'、'.join(r.accepts) or '无'}）"
                 for r in self.routes]
        names = " / ".join(r.name for r in self.routes) or self.default
        return (
            "你是意图分类器。只输出 JSON，不要输出别的。\n"
            f"候选路线：{'；'.join(lines) or self.default}\n"
            f"用户输入：{goal.text}\n"
            f'输出格式：{{"route": "<name>"}}，name 取自：{names}'
        )

    def _parse(self, reply_text: str) -> str | None:
        try:
            data = json.loads(reply_text)
        except (TypeError, ValueError):
            return None
        name = data.get("route") if isinstance(data, dict) else None
        return str(name) if name else None

    async def route(self, goal: Goal) -> Route:
        self.total_count += 1
        by_name = {r.name: r for r in self.routes}
        reply = await self.model.complete([{"role": "user", "content": self._prompt(goal)}])
        name = self._parse(str(getattr(reply, "content", "") or ""))
        if name is None or (name not in by_name and name != self.default):
            self.fallback_count += 1           # 兜底率统计
            name = self.default
        route = by_name.get(name)
        if route is not None:
            return Route(route.name, accepts=list(route.accepts),
                         fallback=route.fallback)
        return Route(self.default, fallback=True)


@dataclass
class VectorRouter:
    """嵌入检索路由：goal 文本查向量库，top1 文档的 source 标注决定路线。

    index 实现 IndexBackend 协议（search/upsert）；入库时把
    source 写成 "route=<name>" 即完成标注（见 impl/backends/vector.py
    的 InMemoryVectorIndex，离线可测）。低于置信阈值或空结果 → fallback。
    """

    index: Any = None
    namespace: Any = None                  # Namespace；缺省按 default 租户
    k: int = 1
    min_score: float = 0.0
    default: str = "general"
    fallback_count: int = 0
    total_count: int = 0

    def _route_of(self, recalled) -> str | None:
        source = str(getattr(recalled, "source", ""))
        for pair in source.split(";"):
            pair = pair.strip()
            if pair.startswith("route="):
                return pair.split("=", 1)[1] or None
        return None

    async def route(self, goal: Goal) -> Route:
        from harness.contracts.types import Namespace

        self.total_count += 1
        ns = self.namespace or Namespace()
        hits = await self.index.search(ns, goal.text, k=self.k)
        if hits:
            top = hits[0]
            score = float(getattr(top, "score", 0.0) or 0.0)
            name = self._route_of(top)
            if name is not None and score >= self.min_score:
                return Route(name)
        self.fallback_count += 1
        return Route(self.default, fallback=True)

    @property
    def fallback_rate(self) -> float:
        """兜底率：两种路由器共用同一统计口径，替换实验可直接对比。"""
        return self.fallback_count / self.total_count if self.total_count else 0.0


LLMRouter.fallback_rate = property(  # 统一口径：LLMRouter 也暴露 fallback_rate
    lambda self: self.fallback_count / self.total_count if self.total_count else 0.0)

