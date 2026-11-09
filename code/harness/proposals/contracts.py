"""通用解释器方案 · 最小契约（提案样张）。

与本方案的第 4 节对应。放在 proposals/ 下，不接入 src/harness，
用途是让 10 种内置范式与自定义架构都能真实跑起来并回归。

设计要点：
  * Program.transition 是纯同步函数，只依赖 State；
    所有 I/O 必须表达成 Effect，由解释器统一执行 —— 这是治理能统一的前提。
  * Decision 里带回"下一个 program"，因此循环/分支/回溯都不是算子，
    只是 program 的取值。
  * 可选能力 describe / to_spec / static_check 构成治理分级：
    框架保证任何程序都能跑，不保证任何程序都可检查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class State:
    """唯一可变状态。单一所有者：只有解释器的 commit 能写它。"""

    goal: str
    data: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    rev: int = 0
    journal: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """只备份可回滚的业务状态。

        journal（观测/消费进度）与 usage（计量）是既成事实，不随回溯回滚 ——
        否则回溯会把"已经问过模型"这件事也撤销，评估脚本会被重复消费。
        """
        import copy

        return copy.deepcopy(
            {"goal": self.goal, "data": self.data, "results": self.results, "rev": self.rev}
        )

    def restore(self, snap: dict[str, Any]) -> None:
        import copy

        self.goal = snap["goal"]
        self.data = copy.deepcopy(snap["data"])
        self.results = copy.deepcopy(snap["results"])
        self.rev = snap["rev"]


@dataclass(frozen=True)
class Effect:
    """一个效应请求：想对外部世界做的一件事，不是立刻做。

    kind 可扩展；本样张内置 model / tool / skill / ask / wait / compute / child。
    """

    kind: str
    spec: dict[str, Any] = field(default_factory=dict)
    key: str = ""


@dataclass(frozen=True)
class Decision:
    effects: tuple[Effect, ...] = ()          # 一批：0 个 = 纯决策步，多个 = 并行
    program: Any = None                        # 下一个程序；None = 保持当前
    patch: dict[str, Any] = field(default_factory=dict)
    restore: dict[str, Any] | None = None     # 回溯：先恢复历史状态再执行
    note: str = ""


@dataclass(frozen=True)
class Halt:
    answer: str = ""
    status: str = "completed"


@runtime_checkable
class Program(Protocol):
    name: str

    def transition(self, state: State) -> Decision | Halt: ...


class FnProgram:
    """零封装入口：把一个裸函数变成 Program。"""

    def __init__(self, fn: Callable[[State], Decision | Halt], name: str = "fn") -> None:
        self.fn = fn
        self.name = name

    def transition(self, state: State) -> Decision | Halt:
        return self.fn(state)


def capabilities(program: Any) -> dict[str, bool]:
    """治理分级：程序声明自己支持哪些静态能力，缺省即降级。"""

    return {
        name: callable(getattr(program, name, None))
        for name in ("describe", "to_spec", "static_check")
    }


def describe(program: Any) -> str:
    fn = getattr(program, "describe", None)
    return fn() if callable(fn) else f"<opaque:{getattr(program, 'name', type(program).__name__)}>"


def to_spec(program: Any) -> dict[str, Any]:
    fn = getattr(program, "to_spec", None)
    if not callable(fn):
        raise TypeError("NotSerializable: 闭包程序不提供 to_spec()")
    return fn()


# ------------------------------------------------------------------ 横切（保留且增强）


def _allow(effect: Effect, state: State) -> str:
    return "allow"


def _noop_check(effect: Effect, state: State) -> None:
    return None


def _identity_wrap(effect: Effect, nxt: Callable) -> Callable:
    return nxt


def _noop_observe(effect: Effect, result: Any, state: State) -> None:
    return None


@dataclass
class Layer:
    """四段链上的横切单元。gate=Gate, check=Check, wrap=Wrap, observe=Hook。

    与现有 harness 的 Layer/Middleware/Hook 协议一一对应；
    本样张只做最小实现，用于证明"组件与 hooks 一个都不删，且插点可扩展"。
    """

    name: str
    gate: Callable[[Effect, State], str] = _allow
    check: Callable[[Effect, State], None] = _noop_check
    wrap: Callable[[Effect, Callable], Callable] = _identity_wrap
    observe: Callable[[Effect, Any, State], None] = _noop_observe


__all__ = [
    "State", "Effect", "Decision", "Halt", "Program", "FnProgram",
    "capabilities", "describe", "to_spec", "Layer",
]
