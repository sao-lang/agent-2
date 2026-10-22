"""第 6 章示例 1：Plan-and-Execute 的执行骨架（不需要 API）。

运行：
    python code/ch06_plan_execute/demo_plan_exec.py

演示三件事：
  1. 计划的依赖关系怎么决定执行顺序（s4 要等 s1、s2）
  2. 后面的步骤怎么引用前面的结果（{s1.result}）
  3. 三步搜索是**互相独立**的——真实系统里应该并行（第 22 章）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.planning import Executor, demo_plan  # noqa: E402


def serial_vs_parallel_sim() -> None:
    """用 sleep 模拟 IO，展示"独立步骤并行"能省多少时间。"""
    print("\n=== 独立步骤：串行 vs 并行 ===")
    steps = 3
    latency = 0.4  # 每次检索 400ms

    t0 = time.perf_counter()
    for i in range(steps):
        time.sleep(latency)
    serial = time.perf_counter() - t0

    import asyncio

    async def one(i: int) -> None:
        await asyncio.sleep(latency)

    async def parallel() -> None:
        await asyncio.gather(*(one(i) for i in range(steps)))

    t0 = time.perf_counter()
    asyncio.run(parallel())
    par = time.perf_counter() - t0

    print(f"  串行：{serial:.2f}s   并行：{par:.2f}s   提速 {serial / par:.1f}x")
    print("  👉 计划图上 s1/s2/s3 没有依赖关系，就该并行。这是 P&E 的隐藏收益。")


def main() -> None:
    plan = demo_plan()

    print("=== 计划 ===")
    for s in plan.steps:
        deps = f"  依赖 {s.depends_on}" if s.depends_on else ""
        print(f"  [{s.id}] {s.goal:<12} action={s.action:<8}{deps}")

    print("\n=== 执行 ===")
    executor = Executor(tools={"search": _tool("search"), "compare": _tool("compare"), "answer": _tool("answer")})
    plan = executor.run(plan)

    print("\n=== 最终结果 ===")
    print(f"  {plan.steps[-1].result}")
    print(f"\n  完成：{plan.is_complete()}   失败步骤：{len(plan.failed())}")

    serial_vs_parallel_sim()

    print("\n👉 注意 s4 的 args 里写的是 {s1.result}——")
    print("   这就是 P&E 和 ReAct 的关键差异：**数据依赖是显式的**，不是藏在消息历史里。")
    print("   显式依赖的三个好处：可并行（无依赖的）、可重试（只重跑失败的）、可解释（一眼看出谁用了谁）。")


def _tool(name: str):
    from common.planning import TOOLS

    return TOOLS[name]


if __name__ == "__main__":
    main()
