"""第 7 / 8 章：主循环。这里没有业务分支，只有五步调度。

    ① 事前闸门 → ② 一次调用 → ③ 记账 → ④ 分派 → ⑤ 终止

文件里不出现任何工具名、字段名、提示词、模型厂商，也不出现 `if verbose`。
要加能力，去 guards / handlers / executor 里加，别回到这里堆 if。
"""

from __future__ import annotations

# ── 第 7 章 B2：主循环 / 第 8 章：预算闸门 ───────────────────────────────────

from typing import Any

from .contracts import ChatClient, RunConfig
from .executor import ToolExecutor
from .guards import GuardSet
from .handlers import StepContext, dispatch
from .state import BUDGET, MAX_STEPS, Reporter, RunState, Stats


def run_loop(
    *,
    client: ChatClient,
    config: RunConfig,
    guards: GuardSet,
    state: RunState,
    reporter: Reporter,
) -> tuple[str, Any, Stats]:
    """返回三样：状态（为什么停）、答复（成功时才有）、统计（验证时要看的数）。"""
    executor = ToolExecutor(config.registry, guards, state, reporter)
    answer: Any = None

    # for-else：循环正常跑完（没 break）才是"步数到顶"（第 7 章 B2）
    for step in range(1, config.max_steps + 1):
        state.step = step
        state.stats.steps = step             # 断点恢复时它就是"从第几步继续"

        # ① 预算闸门在调用之前：已经花掉的钱收不回来
        if guards.budget_exceeded(config.max_prompt_tokens):
            reporter.budget(step, state.stats.prompt_tokens, config.max_prompt_tokens)
            status = BUDGET
            break

        # ② 这就是"一次调用"：四个输入全在这里决定
        turn = client.chat(
            model=config.model,
            messages=state.messages,
            tools=config.tools,
            temperature=config.temperature,
        )

        # ③ 记账 + 把 assistant 消息原样放回历史（回灌时服务端要求它在）
        state.add_usage(turn)
        state.messages.append(turn.as_message())

        # ④ finish_reason 的四条分支交给分派表
        ctx = StepContext(turn, state, guards, config.registry, config, reporter, executor)
        outcome = dispatch(turn.finish_reason, ctx)

        # ⑤ 终止只由 handler 的返回值决定
        if outcome.terminated:
            status, answer = outcome.status, outcome.answer
            break
    else:
        status = MAX_STEPS                   # 可能还能继续，但不让继续了

    reporter.summary(status, state.stats)
    return status, answer, state.stats
