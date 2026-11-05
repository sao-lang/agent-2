"""第 3 / 7 章：一次运行要记住的全部字段（九插点里的 ⑧ 记账）。

Stats 存数字，Reporter 负责打印，RunState 把两者和 messages 绑在一次任务上。
第 24 章的 State 就从这个类长出去。核心只读它们，不在这里写任何业务判断。
"""

from __future__ import annotations

# ── 第 3 章 A4 / 第 7 章 B2：状态常量、记账与打印 ─────────────────────────────

from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import Turn

# 第 7 章 B2：三态（ANSWERED / MAX_STEPS / STALLED）区分"任务没走完"的三种原因，
# 修法各不相同；另外两个（BUDGET / FILTERED）是"不让继续"的外部原因，不属于三态。
# RUNNING 不是终态，是 handler 返回值里"继续下一步"的哨兵。
RUNNING, ANSWERED, MAX_STEPS, STALLED, BUDGET, FILTERED = (
    "RUNNING", "ANSWERED", "MAX_STEPS", "STALLED", "BUDGET", "FILTERED",
)


@dataclass
class Stats:
    """一次运行的全部可观测数字。第 3 章说的"报三个数"就从这里出。"""

    steps: int = 0                 # 走了几步（循环次数，不是工具调用次数）
    tool_calls: int = 0            # 收到几次工具调用请求（含被拦下的重复请求）
    prompt_tokens: int = 0         # 累计输入 token：每步都重发全部历史，涨得最快
    completion_tokens: int = 0     # 累计输出 token：量小，却贡献一半以上成本
    duplicate_blocked: int = 0     # 第 8 章：请求指纹命中的次数
    arg_errors: int = 0            # 第 5 章：参数校验失败次数
    schema_retries: int = 0        # 第 5 章：结构化输出不合法后的重试次数
    truncated: int = 0             # 第 1 章：finish_reason=length 的次数
    trimmed: int = 0               # 第 8 章 B5：单条消息被裁剪的次数
    repeated_result: int = 0       # 第 8 章：结果指纹重复的次数（换参数打转）

    @property
    def total_tokens(self) -> int:
        # 计费口径是"输入 + 输出"，两者单价不同，所以只给总量，不给成本
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Outcome:
    """handler 的返回值：只回答"继续，还是以什么状态停"。

    有了它，主循环就不需要理解 finish_reason 的任何业务含义。
    """

    status: str = RUNNING
    answer: Any = None

    @property
    def terminated(self) -> bool:
        return self.status != RUNNING


@dataclass
class RunState:
    """一次任务的可变状态。守卫与任务一一对应，所以它们不放在这里做单例。"""

    messages: list[dict]
    stats: Stats = field(default_factory=Stats)
    step: int = 0

    def add_usage(self, turn: Turn) -> None:
        """第 3 章 A4：计费只认服务端 usage，本地估算只用于兜底。"""
        self.stats.prompt_tokens += turn.prompt_tokens
        self.stats.completion_tokens += turn.completion_tokens


class Reporter:
    """把所有 print 收在一处：核心、守卫、执行器里不再出现 `if verbose`。

    关掉 verbose 只应该让输出消失，不该改变任何计数或分支——这正是
    "关掉一个开关只有一件事变"的最小例子。
    """

    def __init__(
        self,
        verbose: bool = True,
        describe_answer: Callable[[Any], str] = str,
    ) -> None:
        self.verbose = verbose
        self.describe_answer = describe_answer

    def _emit(self, line: str) -> None:
        if self.verbose:
            print(line)

    # ── 每一步的痕迹（第 8 章：排查时按时间顺序看这些行）──
    def duplicate(self, step: int, name: str) -> None:
        self._emit(f"  步 {step} 工具 {name}：重复指纹被拦下")

    def unknown_tool(self, step: int, name: str) -> None:
        self._emit(f"  步 {step} 工具 {name}：未声明的工具名，已回灌错误")

    def arg_error(self, step: int, name: str) -> None:
        self._emit(f"  步 {step} 工具 {name}：参数解析失败，已回灌错误")

    def tool_error(self, step: int, name: str, exc: Exception) -> None:
        self._emit(f"  步 {step} 工具 {name}：业务错误 -> {exc}")

    def same_result(self, step: int, name: str) -> None:
        self._emit(f"  步 {step} 工具 {name}：结果与上一次完全相同")

    def tool_ok(self, step: int, name: str, payload: str) -> None:
        self._emit(f"  步 {step} 工具 {name}：{payload[:70]}")

    def budget(self, step: int, used: int, limit: int) -> None:
        self._emit(f"  步 {step} 预算用尽：{used} > {limit}")

    def filtered(self, step: int) -> None:
        self._emit(f"  步 {step} 中止：content_filter，重试无效")

    def truncated(self, step: int) -> None:
        self._emit(f"  步 {step} 截断：已回灌续写指令")

    def schema_retry(self, step: int) -> None:
        self._emit(f"  步 {step} 结构化输出不合法，回灌字段三列")

    def answered(self, step: int, answer: Any) -> None:
        self._emit(f"  步 {step} 结构化输出通过：{self.describe_answer(answer)}")

    def stalled(self, step: int, reason: str) -> None:
        self._emit(f"  步 {step} 判定空转：{reason}")

    def summary(self, status: str, stats: Stats) -> None:
        """第 3 章"三个数"：token / 步数 / 工具调用，后面是各章验证要看的信号。"""
        self._emit(
            f"  结果：status={status} 步数={stats.steps} 工具调用={stats.tool_calls} "
            f"token={stats.prompt_tokens}+{stats.completion_tokens}={stats.total_tokens} "
            f"重复拦截={stats.duplicate_blocked} 参数错误={stats.arg_errors} "
            f"结构化重试={stats.schema_retries} 截断={stats.truncated} 裁剪={stats.trimmed} "
            f"结果重复={stats.repeated_result}"
        )
