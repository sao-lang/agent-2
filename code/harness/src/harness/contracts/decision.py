"""通用解释器的唯一契约（v3 / PROPOSAL §4）。

框架不提供任何架构，只提供这套最小执行契约：

    Program.transition(state) -> Decision | Halt

`Decision` 描述「一批效应 + 下一个程序 + 状态增量」；内核只负责循环、
批量执行效应、提交状态、发事件/检查点、换下一个程序。顺序、分支、循环、
并行、回溯、图、谁持有控制权，全部由 ``program`` 决定。

**命名说明**：本模块里的 ``Decision`` 是「转移决策」。现有
``harness.contracts.types.Decision`` 是「人工审批结果」，语义不同且被
``ApprovalChannel`` / ``Agent.resume`` 依赖，因此两者保持命名空间隔离：
顶层 ``harness.Decision`` 仍是审批类型，本类型通过
``harness.contracts.decision.Decision`` 使用，顶层别名为 ``Transition``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from harness.contracts.errors import NotSerializable
from harness.contracts.protocols.runtime import Program
from harness.contracts.state import State
from harness.contracts.types import Effect

__all__ = [
    "Decision",
    "Halt",
    "Program",
    "FnProgram",
    "CAPABILITIES",
    "capabilities",
    "describe",
    "to_spec",
    "static_problems",
]


@dataclass(frozen=True)
class Decision:
    """一次转移。

    effects   一批效应请求：0 个 = 纯决策步，多个 = 并行
    program   下一个程序；None = 保持当前（自己 = 循环，历史 = 回溯，新组合 = 改图）
    patch     显式状态增量，由解释器在唯一提交点写入
    restore   回溯：先恢复历史快照再执行（journal/usage 不回滚）
    meta      透传给效应运行时的附加信息（如旧路径的事件字段），内核不解释
    """

    effects: tuple[Effect, ...] = ()
    program: Any = None
    patch: dict[str, Any] = field(default_factory=dict)
    restore: dict[str, Any] | None = None
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Halt:
    """终止。status 用字符串，允许前端自定义状态而不改内核。"""

    answer: str = ""
    status: str = "completed"
    extra: dict[str, Any] = field(default_factory=dict)


class FnProgram:
    """零封装入口：把一个裸函数（可同步可异步）变成 Program。"""

    def __init__(self, fn: Callable[[State], Decision | Halt], name: str = "fn") -> None:
        self.fn = fn
        self.name = name

    def transition(self, state: State) -> Decision | Halt:
        return self.fn(state)


#: 程序可声明的静态能力；缺省即降级（PROPOSAL §4.2 治理分级）。
CAPABILITIES = ("describe", "to_spec", "static_check")


def capabilities(program: Any) -> dict[str, bool]:
    """程序声明自己支持哪些静态能力，框架不假装全能。"""
    return {name: callable(getattr(program, name, None)) for name in CAPABILITIES}


def describe(program: Any) -> str:
    fn = getattr(program, "describe", None)
    return fn() if callable(fn) else f"<opaque:{getattr(program, 'name', type(program).__name__)}>"


def to_spec(program: Any) -> dict[str, Any]:
    """检查点序列化。闭包程序显式降级，不假装支持时间旅行。"""
    fn = getattr(program, "to_spec", None)
    if not callable(fn):
        raise NotSerializable("NotSerializable: 闭包程序不提供 to_spec()")
    return fn()


def static_problems(program: Any) -> list[str]:
    """装配期可查的都查；不透明程序返回空列表（运行时治理）。"""
    check = getattr(program, "static_check", None)
    return list(check()) if callable(check) else []
