"""框架作者没想过的架构（v3 / PROPOSAL §8）—— **纯用户侧代码**。

这四个架构全部写在 examples/ 里，只导入框架的公开契约与公开运行时：
``contracts/decision.py`` 与 ``kernel/interpret.py`` 一行不改就能跑。

* Backtrack       回溯搜索（ToT / LATS）：恢复快照 + 换分支
* SelfModifying   运行时自改写控制流：下一轮程序由运行结果决定
* ExternalControl 控制权交给外部系统：程序只发 wait 效应
* BareFunction    零封装：一个裸函数就是架构

运行：
    cd code/harness
    PYTHONPATH=src python examples/unknown_architectures.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

if __package__ in (None, ""):  # 允许直接 python examples/xxx.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.contracts.decision import Decision, FnProgram, Halt  # noqa: E402
from harness.contracts.state import State  # noqa: E402
from harness.contracts.types import Effect  # noqa: E402
from harness.fp.frontends import _batch, _out, make_state, toolset  # noqa: E402
from harness.kernel.interpret import Limits, Runtime  # noqa: E402


@dataclass(frozen=True)
class Backtrack:
    """试一个分支 → 评估 → 不合格就恢复快照、换下一分支。"""

    name: ClassVar[str] = "backtrack"
    branches: tuple[str, ...] = ("alpha", "beta", "gamma")
    snapshots: tuple[dict, ...] = ()
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
                effects=(Effect("compute", args={"op": "upper", "args": [branch]},
                                key="candidate"),),
                program=replace(self, phase="evaluate", snapshots=self.snapshots + (snap,)),
                note=f"try {branch}",
            )
        verdict = _out(_batch(state), "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="evaluate")
        candidate = state.results.get("candidate", {}).get("output", "")
        if isinstance(verdict, dict) and verdict.get("verdict") == "pass":
            return Halt(str(candidate))
        return Decision(effects=(),
                        program=replace(self, index=self.index + 1, phase="try"),
                        restore=self.snapshots[-1], note="backtrack")


@dataclass(frozen=True)
class SelfModifying:
    """运行时重排剩余控制流 —— 图不是装配期定的，是跑出来的。"""

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
            effects=(Effect("compute", args={"op": "upper", "args": [head]}, key="last"),),
            program=nxt, patch={"last_node": head}, note=f"gen{self.generation}:{head}",
        )


@dataclass(frozen=True)
class ExternalControl:
    """程序只发 wait 效应，外部队列给什么指令就做什么。"""

    name: ClassVar[str] = "external_control"
    hops: int = 0

    def describe(self) -> str:
        return f"external_control(hops={self.hops})"

    def transition(self, state: State) -> Decision | Halt:
        command = _out(_batch(state), "cmd")
        if command is None:
            return Decision(effects=(Effect("wait", key="cmd"),), program=self,
                            note="await external")
        if command == "stop":
            return Halt(f"外部系统叫停（执行了 {self.hops} 条指令）")
        return Decision(
            effects=(Effect("compute", args={"op": "upper", "args": [str(command)]},
                            key="last"),),
            program=replace(self, hops=self.hops + 1), note=f"follow {command}",
        )


def bare_transition(state: State) -> Decision | Halt:
    """零封装：不写类，一个函数就是架构。"""
    return Decision(
        effects=(Effect("compute", args={"op": "concat", "args": ["裸", "函数"]}, key="last"),),
        program=FnProgram(lambda s: Halt(str(s.data.get("last_output", ""))), name="bare_end"),
        note="零封装",
    )


def custom_cases() -> list[tuple[str, Any, State]]:
    queue: asyncio.Queue = asyncio.Queue()
    for command in ("alpha", "beta", "stop"):
        queue.put_nowait(command)
    return [
        ("ⓐ Backtrack（回溯搜索）", Backtrack(), make_state("搜索", data={
            "tools": toolset(), "script": [{"verdict": "fail"}, {"verdict": "pass"}],
        })),
        ("ⓑ SelfModifying（运行时改图）", SelfModifying(), make_state("动态编排", data={
            "tools": toolset(), "promote": "n1",
        })),
        ("ⓒ ExternalControl（外部主导）", ExternalControl(), make_state("外部驱动", data={
            "tools": toolset(), "external_queue": queue,
        })),
        ("ⓓ BareFunction（零封装）", FnProgram(bare_transition, name="bare"),
         make_state("裸函数", data={"tools": toolset()})),
    ]


async def main() -> None:
    for name, program, state in custom_cases():
        out = await Runtime(limits=Limits(max_transitions=64, max_calls=80)).interpret(
            program, state
        )
        print(f"[{out.status}] {name} steps={out.transitions} answer={out.answer!r}")
        print("      " + " > ".join(out.trace[:6]))


__all__ = [
    "Backtrack", "SelfModifying", "ExternalControl", "bare_transition", "custom_cases",
]


if __name__ == "__main__":
    asyncio.run(main())
