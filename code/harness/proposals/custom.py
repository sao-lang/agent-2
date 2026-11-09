"""通用解释器方案 · 使用其他架构的范式（提案样张）。

对应方案第 8 节。这四个架构**框架作者没有预先想过**，
全部只写在用户侧，contracts.py / interpreter.py 一行不改：
  * Backtrack        回溯搜索（ToT / LATS）：恢复历史 State + 历史 Program
  * SelfModifying    运行时自改写控制流
  * ExternalControl  控制权交给外部系统（actor / 事件驱动）
  * BareFunction     不封装，直接一个函数当 program
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from proposals.contracts import Decision, Effect, FnProgram, Halt, State
from proposals.paradigms import Leaf, _out, _batch, toolset


@dataclass(frozen=True)
class Backtrack:
    """树搜索：试一个分支 → 评估 → 不合格就恢复快照、换下一分支。

    框架不需要 backtrack 算子：restore + program 的取值就够了。
    """

    name: ClassVar[str] = "backtrack"
    branches: tuple[str, ...] = ("alpha", "beta", "gamma")
    snapshots: tuple[dict[str, Any], ...] = ()
    index: int = 0
    phase: str = "try"

    def describe(self) -> str:
        return f"backtrack(branch={self.index}, phase={self.phase})"

    def transition(self, state: State) -> Decision | Halt:
        if self.phase == "try":
            if self.index >= len(self.branches):
                return Halt("所有分支均失败", "failed")
            snap = state.snapshot()
            branch = self.branches[self.index]
            return Decision(
                effects=(Effect("compute", {"op": "upper", "args": [branch]}, key="candidate"),),
                program=replace(self, phase="evaluate", snapshots=self.snapshots + (snap,)),
                note=f"try {branch}",
            )
        verdict = _out(_batch(state), "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="evaluate")
        candidate = state.results.get("candidate", {}).get("output", "")
        if isinstance(verdict, dict) and verdict.get("verdict") == "pass":
            return Halt(str(candidate))
        return Decision(
            effects=(),
            program=replace(self, index=self.index + 1, phase="try"),
            restore=self.snapshots[-1], note="backtrack",
        )


@dataclass(frozen=True)
class SelfModifying:
    """运行时改图：每轮组装一个新的 program（剩余节点可被重排）。"""

    name: ClassVar[str] = "self_modifying"
    remaining: tuple[str, ...] = ("n1", "n2", "n3")
    generation: int = 0

    def describe(self) -> str:
        return f"self_modifying(gen={self.generation}, remaining={len(self.remaining)})"

    def transition(self, state: State) -> Decision | Halt:
        if not self.remaining:
            return Halt(f"动态图执行完毕（共 {self.generation} 代）")
        head, *tail = list(self.remaining)
        if state.data.get("promote") == head:
            tail = list(reversed(tail))
        nxt = replace(self, remaining=tuple(tail), generation=self.generation + 1)
        return Decision(
            effects=(Effect("compute", {"op": "upper", "args": [head]}, key="last"),),
            program=nxt, patch={"last_node": head}, note=f"gen{self.generation}:{head}",
        )


@dataclass(frozen=True)
class ExternalControl:
    """控制权在外部：程序只发 wait 效应，外部队列给什么指令就做什么。

    所有 I/O 仍是 Effect —— 这正是"外部主导"也能被统一治理的原因。
    """

    name: ClassVar[str] = "external_control"
    hops: int = 0

    def describe(self) -> str:
        return f"external_control(hops={self.hops})"

    def transition(self, state: State) -> Decision | Halt:
        command = _out(_batch(state), "cmd")
        if command is None:
            return Decision(effects=(Effect("wait", key="cmd"),), program=self, note="await external")
        if command == "stop":
            return Halt(f"外部系统叫停（执行了 {self.hops} 条指令）")
        return Decision(
            effects=(Effect("compute", {"op": "upper", "args": [str(command)]}, key="last"),),
            program=replace(self, hops=self.hops + 1), note=f"follow {command}",
        )


def bare_transition(state: State) -> Decision | Halt:
    """零封装：不写类，一个函数就是架构。"""

    return Decision(
        effects=(Effect("compute", {"op": "concat", "args": ["裸", "函数"]}, key="last"),),
        program=FnProgram(lambda s: Halt(str(s.data.get("last_output", ""))), name="bare_end"),
        note="零封装",
    )


def custom_cases() -> list[tuple[str, Any, State]]:
    queue: asyncio.Queue = asyncio.Queue()
    for command in ("alpha", "beta", "stop"):
        queue.put_nowait(command)

    return [
        ("ⓐ Backtrack（回溯搜索）", Backtrack(), State("搜索", data={
            "tools": toolset(), "script": [{"verdict": "fail"}, {"verdict": "pass"}],
        })),
        ("ⓑ SelfModifying（运行时改图）", SelfModifying(), State("动态编排", data={
            "tools": toolset(), "promote": "n1",
        })),
        ("ⓒ ExternalControl（外部主导）", ExternalControl(), State("外部驱动", data={
            "tools": toolset(), "external_queue": queue,
        })),
        ("ⓓ BareFunction（零封装）", FnProgram(bare_transition, name="bare"), State("裸函数", data={
            "tools": toolset(),
        })),
    ]


__all__ = [
    "Backtrack", "SelfModifying", "ExternalControl", "bare_transition", "custom_cases",
]
