"""分派层：请求走哪条路。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import Goal, Route


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
