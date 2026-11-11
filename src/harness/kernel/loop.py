"""兼容壳：v2 循环已降级为 React 前端（PROPOSAL §9.3 / §10）。

**这里不再有循环。** 全框架唯一的循环是 ``kernel.interpret.Runtime.interpret``；
``run_loop`` 只把旧签名转发给 ``kernel.legacy.run_legacy``，后者把
``body.next_step`` 编译成 ``transition``，并用 ``Effect → Step`` 适配器
喂给既有四段链。签名、事件、RunResult 语义保持不变。
"""

from __future__ import annotations

from typing import Any

from harness.contracts.result import RunResult
from harness.contracts.state import State

__all__ = ["run_loop"]


async def run_loop(*, program: Any, state: State, scope: Any,
                   record_effects: list | None = None,
                   max_transitions: int | None = None) -> RunResult:
    from harness.kernel.legacy import run_legacy

    return await run_legacy(program=program, state=state, scope=scope,
                            record_effects=record_effects,
                            max_transitions=max_transitions)
