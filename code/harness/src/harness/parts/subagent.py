"""子 agent 层（SPEC M13.5）。

五条必须做全，缺一条就是玩具：
    1 独立作用域：新 Namespace、新 State、span 挂父
    2 共享预算：child = parent.split(0.3)，消耗仍计入父
    3 上限：深度、并发、子树步数
    4 返回摘要：只回 answer + 引用 + 用量，**不回灌 messages**
    5 取消传播：父取消 → 子全停
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Awaitable, Callable

from harness.contracts.types import Goal, TaskSpec, ToolRequest, ToolResponse, ToolResult
from harness.parts.middleware.base import Layer, layer

DEFAULT_TOOL = "task"


def subagent_layer(
    *,
    scope: Any,
    agent_factory: Callable[[Any, TaskSpec], Any],
    tool_name: str = DEFAULT_TOOL,
    concurrency: int = 4,
    budget_fraction: float = 0.3,
    max_summary_chars: int = 2000,
) -> Layer:
    """插点 tool_call：把 `task` 工具变成一次子运行。

    `agent_factory(child_scope, task)` 返回一个带 `run(goal, scope)` 的 Runnable。
    """

    slots = scope.child_slots or asyncio.Semaphore(max(1, concurrency))
    if scope.child_slots is None:
        # 第一次构造时把槽位钉进作用域，后续所有子层共用同一份（不变量 2）
        scope = replace(scope, child_slots=slots)

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ToolRequest) or req.step.tool_name != tool_name:
                return await nxt(req)

            args = dict(req.step.args or {})
            task = TaskSpec(
                description=str(args.get("description", req.step.instruction or "")),
                agent_type=str(args.get("agent_type", "default")),
                expected_schema=args.get("expected_schema"),
            )
            if not task.description.strip():
                return ToolResponse(
                    result=ToolResult(step_id=req.step.id, tool=tool_name, ok=False,
                                      error="缺少 description")
                )

            child_scope = scope.child(task.agent_type, budget_fraction=budget_fraction)
            async with slots:                                  # ③ 并发上限
                child = agent_factory(child_scope, task)
                try:
                    result = await child.run(Goal(task.description, session_id=req.step.id), scope=child_scope)
                except asyncio.CancelledError:                  # ⑤ 取消传播
                    raise

            summary = (result.answer or "")[:max_summary_chars]
            return ToolResponse(
                result=ToolResult(                                                    # ④ 只回摘要
                    step_id=req.step.id,
                    tool=tool_name,
                    ok=result.status in ("completed", "degraded"),
                    output=summary,
                    error=result.error,
                    tokens=int(result.usage.get("tokens", 0)),
                    meta={
                        "depth": child_scope.depth,
                        "agent": child_scope.namespace.agent,
                        "status": str(result.status),
                        "usage": dict(result.usage),
                    },
                )
            )

        return handler

    return layer("subagent", ["tool_call"], build,
                 needs=["durability", "sandbox", "budget"], after=["approval"])


async def run_child(
    factory: Callable[[Any, TaskSpec], Any],
    scope: Any,
    task: TaskSpec,
) -> Any:
    """便捷入口：不经过工具，直接起一次子运行（拓扑内部也会用到）。"""
    child_scope = scope.child(task.agent_type)
    child = factory(child_scope, task)
    return await child.run(Goal(task.description), scope=child_scope)


__all__ = ["subagent_layer", "run_child", "DEFAULT_TOOL"]
