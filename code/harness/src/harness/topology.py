"""拓扑：只组合 Agent，不实现能力。"""

from __future__ import annotations

from typing import Any, Callable

from .contracts import Goal, RunStatus, SessionRef
from .result import RunResult


def _merge_usage(results: list[RunResult]) -> dict[str, int]:
    return {
        "tokens": sum(item.usage.get("tokens", 0) for item in results),
        "calls": sum(item.usage.get("calls", 0) for item in results),
    }


def _last_state(results: list[RunResult]):
    return results[-1].state if results else None


class Pipeline:
    """顺序执行；上一阶段的 answer 作为下一阶段的 goal。"""

    name = "pipeline"

    def __init__(self, stages: list[Any]) -> None:
        self.stages = list(stages)

    async def run(self, goal: Goal, session: SessionRef | None = None) -> RunResult:
        current = goal
        results: list[RunResult] = []
        for stage in self.stages:
            result = await stage.run(current, session)
            results.append(result)
            if result.status not in (RunStatus.COMPLETED, RunStatus.DEGRADED):
                return result
            current = Goal(
                text=result.answer,
                user_id=goal.user_id,
                session_id=goal.session_id,
                metadata=goal.metadata,
            )
        if not results:
            return RunResult(status=RunStatus.FAILED, error="pipeline 没有阶段")
        last = results[-1]
        return RunResult(
            status=last.status,
            answer=last.answer,
            state=last.state,
            usage=_merge_usage(results),
            citations=last.citations,
            trace_id=last.trace_id,
        )


class Handoff:
    """按 Router 把控制权交给一个 agent。"""

    name = "handoff"

    def __init__(self, agents: dict[str, Any], router) -> None:
        self.agents = dict(agents)
        self.router = router

    async def run(self, goal: Goal, session: SessionRef | None = None) -> RunResult:
        route = await self.router.route(goal)
        agent = self.agents.get(route.name)
        if agent is None:
            for name, item in self.agents.items():
                if getattr(item, "is_fallback", False):
                    agent = item
                    break
        if agent is None:
            return RunResult(status=RunStatus.REFUSED, error=f"没有匹配的 agent：{route.name}")
        return await agent.run(goal, session)


class Supervisor:
    """按计划把子任务派给 worker，再汇总。"""

    name = "supervisor"

    def __init__(self, workers: dict[str, Any], plan: Callable[[Goal], list[tuple[str, str]]],
                 synth: Callable[[dict[str, RunResult]], str] | None = None) -> None:
        self.workers = dict(workers)
        self.plan = plan
        self.synth = synth

    async def run(self, goal: Goal, session: SessionRef | None = None) -> RunResult:
        results: dict[str, RunResult] = {}
        for name, subtask in self.plan(goal):
            if name not in self.workers:
                return RunResult(status=RunStatus.FAILED, error=f"未知 worker：{name}")
            results[name] = await self.workers[name].run(
                Goal(
                    text=subtask,
                    user_id=goal.user_id,
                    session_id=goal.session_id,
                    metadata=goal.metadata,
                ),
                session,
            )
            if results[name].status not in (RunStatus.COMPLETED, RunStatus.DEGRADED):
                return results[name]

        if self.synth is not None:
            answer = self.synth(results)
        else:
            answer = "\n".join(item.answer for item in results.values() if item.answer)

        last = list(results.values())[-1] if results else None
        return RunResult(
            status=RunStatus.COMPLETED,
            answer=answer,
            state=last.state if last else None,
            usage=_merge_usage(list(results.values())),
            citations=last.citations if last else [],
            trace_id=last.trace_id if last else "",
        )


class Blackboard:
    """共享看板；顺序写入，reducer 合并。"""

    name = "blackboard"

    def __init__(self, agents: list[Any], reducer: Callable[[dict[str, str]], str],
                 trigger: Callable[[dict[str, str]], bool] | None = None) -> None:
        self.agents = list(agents)
        self.reducer = reducer
        self.trigger = trigger

    async def run(self, goal: Goal, session: SessionRef | None = None) -> RunResult:
        board: dict[str, str] = {}
        results: list[RunResult] = []
        for index, agent in enumerate(self.agents):
            result = await agent.run(goal, session)
            results.append(result)
            board[f"{getattr(agent, 'name', 'agent')}-{index}"] = result.answer
            if self.trigger and self.trigger(board):
                break
        return RunResult(
            status=RunStatus.COMPLETED if results else RunStatus.FAILED,
            answer=self.reducer(board) if board else "",
            state=_last_state(results),
            usage=_merge_usage(results),
            trace_id=results[-1].trace_id if results else "",
        )
