"""最小通用解释器示例（v3 / PROPOSAL §3）。

三行就能跑：写一个 ``transition``，发一批 ``Effect``，返回下一个 program。
框架不提供架构，架构就是你写的这个程序。

运行：
    cd code/harness
    PYTHONPATH=src python examples/interpret_minimal.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许直接 python examples/xxx.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.contracts.decision import Decision, FnProgram, Halt  # noqa: E402
from harness.contracts.state import State  # noqa: E402
from harness.contracts.types import Effect  # noqa: E402
from harness.fp.frontends import Leaf, React, make_state  # noqa: E402
from harness.kernel.interpret import interpret  # noqa: E402


def step_one(state: State) -> Decision | Halt:
    """一批两个效应 = 并行；program 换成 Leaf = 结束。"""
    return Decision(
        effects=(
            Effect("compute", args={"op": "concat", "args": ["通用", "解释器"]}, key="a"),
            Effect("compute", args={"op": "upper", "args": ["effects"]}, key="b"),
        ),
        program=FnProgram(lambda s: Halt(f"{s.results['a']['output']} / "
                                         f"{s.results['b']['output']}"), name="join"),
        note="fan-out 2",
    )


async def main() -> None:
    # ① 最小程序：一个裸函数
    out = await interpret(FnProgram(step_one, name="minimal"), make_state("最小示例"))
    print(f"minimal: {out.status} {out.answer!r} steps={out.transitions}")
    print("  " + " > ".join(out.trace))

    # ② 内置前端：ReAct 只是 program=self 的循环，同样走这一个 interpret()
    out = await interpret(React(max_steps=4), make_state("查订单", data={
        "script": [{"content": "完成"}],
    }))
    print(f"react:   {out.status} {out.answer!r} steps={out.transitions}")

    # ③ 任何叶子程序都同层：删掉整个 frontends.py，①②照样跑
    out = await interpret(Leaf("同类同接口"), make_state("leaf"))
    print(f"leaf:    {out.status} {out.answer!r} steps={out.transitions}")


if __name__ == "__main__":
    asyncio.run(main())
