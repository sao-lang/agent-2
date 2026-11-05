"""第 1 章 A2：finish_reason 的四条分支，拆成一张分派表。

原来 run() 里是一串 `if finish == ... elif ...`，四个分支夹着工具执行、校验、
守卫和打印。现在每个取值对应一个 handler，主循环只问一句"继续还是停"。

新增一个 finish_reason = 在 HANDLERS 里加一行，主循环一行不用改。
这正是第 8 章"守卫可以随时增加判据而不影响调用方"的落法。
"""

from __future__ import annotations

# ── 第 1 章 A2：finish_reason 分派表 ─────────────────────────────────────────

from dataclasses import dataclass
from typing import Callable

from pydantic import ValidationError

from .contracts import ROLE_USER, RunConfig, ToolRegistry, Turn, to_feedback
from .executor import ToolExecutor
from .guards import GuardSet
from .state import (
    ANSWERED,
    FILTERED,
    STALLED,
    Outcome,
    Reporter,
    RunState,
)


@dataclass
class StepContext:
    """一次循环步交给 handler 的全部东西：只读上下文 + 可追加的 messages。"""

    turn: Turn
    state: RunState
    guards: GuardSet
    registry: ToolRegistry
    config: RunConfig
    reporter: Reporter
    executor: ToolExecutor


FinishHandler = Callable[[StepContext], Outcome]


# ── 分支一：被内容过滤。产物为空，且重试无效（同一输入大概率还是被过滤）──
def handle_content_filter(ctx: StepContext) -> Outcome:
    ctx.reporter.filtered(ctx.state.step)
    return Outcome(FILTERED)


# ── 分支二：输出被 max_tokens 截断。产物不完整，重试无效，要"续写" ──────────
def handle_length(ctx: StepContext) -> Outcome:
    ctx.state.stats.truncated += 1       # 截断是最难发现的失效：它不报错
    # 第 1 章"length 的三种补法"之一：回灌续写指令，让模型接着写
    ctx.state.messages.append({"role": ROLE_USER, "content": ctx.config.continuation_hint})
    ctx.reporter.truncated(ctx.state.step)
    return Outcome()                     # 还能救，所以是 continue 不是 break


# ── 分支三：模型请求执行工具。逐个调用交给 ToolExecutor，再问守卫要不要停 ───
def handle_tool_calls(ctx: StepContext) -> Outcome:
    ctx.executor.execute(ctx.turn.tool_calls)
    reason = ctx.guards.stall_reason()
    if reason:
        ctx.reporter.stalled(ctx.state.step, reason)
        return Outcome(STALLED)
    return Outcome()


# ── 分支四（默认）：没有工具调用 = 模型给了最终答复，唯一可能成功的分支 ─────
def handle_final(ctx: StepContext) -> Outcome:
    raw = (ctx.turn.content or "").strip()
    try:
        # 结构化校验：语法 + 结构一起做；第三层（语义）要靠外部裁判，这里做不到
        answer = ctx.config.output_model.model_validate_json(raw)
    except ValidationError as exc:
        ctx.state.stats.schema_retries += 1
        ctx.state.messages.append({"role": ROLE_USER, "content": to_feedback(exc)})
        ctx.reporter.schema_retry(ctx.state.step)
        return Outcome()
    ctx.reporter.answered(ctx.state.step, answer)
    return Outcome(ANSWERED, answer)


HANDLERS: dict[str, FinishHandler] = {
    "content_filter": handle_content_filter,
    "length": handle_length,
    "tool_calls": handle_tool_calls,
    "stop": handle_final,
}

# 未知取值沿用原来的行为：当作"给了最终答复"处理，让 schema 校验去发现它不对
DEFAULT_HANDLER: FinishHandler = handle_final


def dispatch(finish_reason: str, ctx: StepContext) -> Outcome:
    return HANDLERS.get(finish_reason, DEFAULT_HANDLER)(ctx)
