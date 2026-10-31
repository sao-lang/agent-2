"""第 40 章 · Workflow 的四种坏法与它们报的错。

运行：
    $env:PYTHONPATH="$PWD\\.libs"; $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch40_llamaindex_workflow/workflow_errors.py

每种坏法单独一个 Workflow 子类，看它抛哪个异常、消息里带什么信息。
异常都在 run() 前后抛出，不需要真实模型。
"""

from __future__ import annotations

import asyncio

from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)


class Notify(Event):
    text: str


class MissingStop(Workflow):
    @step
    async def only(self, ctx: Context, ev: StartEvent) -> Notify:
        return Notify(text="做完了，但没人接收")


class Slow(Workflow):
    @step
    async def slow(self, ev: StartEvent) -> StopEvent:
        await asyncio.sleep(2)
        return StopEvent(result="终于好了")


class Orphan(Event):
    n: int


class OrphanFlow(Workflow):
    @step
    async def first(self, ev: StartEvent) -> Orphan:
        return Orphan(n=1)

    @step
    async def last(self, ev: StartEvent) -> StopEvent:
        return StopEvent(result="走另一条路")


class StartVec(Event):
    query: str


class StartKey(Event):
    query: str


class VecDone(Event):
    ids: list[str]


class SentButUndeclared(Workflow):
    """start 用 send_event 发了 StartVec，但没有任何步骤声明“返回 StartVec”。"""

    @step
    async def start(self, ctx: Context, ev: StartEvent) -> StartKey:
        ctx.send_event(StartVec(query="退货运费"))
        return StartKey(query="退货运费")

    @step
    async def vec(self, ev: StartVec) -> VecDone:
        return VecDone(ids=[])

    @step
    async def key(self, ev: StartKey) -> VecDone:
        return VecDone(ids=[])

    @step
    async def done(self, ev: VecDone) -> StopEvent:
        return StopEvent(result="合并完成")


class Boom(Workflow):
    @step
    async def a(self, ev: StartEvent) -> StopEvent:
        raise ValueError("切块器收到空文档")


async def main() -> None:
    print("=== 1. 没有任何步骤返回 StopEvent ===")
    try:
        await MissingStop(timeout=1).run()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {e}")

    print("=== 2. 步骤比超时慢 ===")
    try:
        await Slow(timeout=0.5).run()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {e}")

    print("=== 3. 事件产出后没人消费 ===")
    try:
        await OrphanFlow(timeout=1).run()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {e}")

    print("=== 4. send_event 发了，但没有步骤声明返回它 ===")
    try:
        await SentButUndeclared(timeout=1).run()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {e}")

    print("=== 5. 步骤里抛异常 ===")
    try:
        await Boom(timeout=1).run()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
