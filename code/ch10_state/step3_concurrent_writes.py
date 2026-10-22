"""第 10 章 step3：并发写同一个字段，数据去哪了（离线，真 LangGraph + 真 asyncio）。

运行：
    python code/ch10_state/step3_concurrent_writes.py

上一级的痛点：字段定好了，但多个分支同时写它时，谁赢？

这一级做什么，四段：
  ① 裸 dict + asyncio：3 个协程 append，看丢多少条
  ② 加锁后：一条不丢，但慢了
  ③ langgraph 两个分支写同一字段：不加 reducer → 抛 InvalidUpdateError
  ④ 加 reducer：三条都在，且顺序可控

结论：**State 的并发安全不是"小心点"，是"结构上就写不错"。**
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.errors import InvalidUpdateError  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Send  # noqa: E402

N_APPEND = 300


# ---------------------------------------------------------------- ①/② 裸 dict

async def append_without_lock(bucket: list, worker: int) -> None:
    for i in range(N_APPEND):
        # 模拟"读-改-写"之间被打断：await 一个极短的点
        current = list(bucket)
        await asyncio.sleep(0)
        current.append(f"w{worker}-{i}")
        bucket[:] = current


async def append_with_lock(bucket: list, worker: int, lock: asyncio.Lock) -> None:
    for i in range(N_APPEND):
        async with lock:
            bucket.append(f"w{worker}-{i}")
            await asyncio.sleep(0)


async def demo_asyncio() -> None:
    print("=" * 78)
    print("① 裸 dict + 3 个协程同时 append")
    print("=" * 78)
    bucket: list[str] = []
    await asyncio.gather(*(append_without_lock(bucket, w) for w in range(3)))
    print(f"  期望 {N_APPEND * 3} 条，实际 {len(bucket)} 条，丢了 {N_APPEND * 3 - len(bucket)} 条")

    print("\n" + "=" * 78)
    print("② 加锁后")
    print("=" * 78)
    bucket2: list[str] = []
    lock = asyncio.Lock()
    await asyncio.gather(*(append_with_lock(bucket2, w, lock) for w in range(3)))
    print(f"  期望 {N_APPEND * 3} 条，实际 {len(bucket2)} 条，丢了 {N_APPEND * 3 - len(bucket2)} 条")
    print("  → 锁能修好，但它把并发变成了串行：每一步都要等锁。")


# ---------------------------------------------------------------- ③/④ LangGraph

class NoReducer(TypedDict, total=False):
    task: str
    subtasks: list[str]
    facts: list[str]          # ⚠️ 没有 reducer


def _merge(left: list, right: list) -> list:
    return (left or []) + (right or [])


class WithReducer(TypedDict, total=False):
    task: str
    subtasks: list[str]
    facts: Annotated[list[str], _merge]


def fan_out(state) -> list:
    return [Send("worker", {"sub": s}) for s in state.get("subtasks", [])]


def build(schema, worker) -> object:
    g = StateGraph(schema)
    g.add_node("plan", lambda s: {"subtasks": ["A", "B", "C"]})
    g.add_node("worker", worker)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["worker"])
    g.add_edge("worker", END)
    return g.compile()


def worker_no_reducer(state: dict) -> dict:
    return {"facts": [f"{state['sub']}:定价 99"]}


def worker_with_reducer(state: dict) -> dict:
    return {"facts": [f"{state['sub']}:定价 99"]}


def demo_langgraph() -> None:
    print("\n" + "=" * 78)
    print("③ langgraph：三个分支同时写 facts，不加 reducer")
    print("=" * 78)
    try:
        out = build(NoReducer, worker_no_reducer).invoke({"task": "对比三家"})
        print(f"  居然成功了？facts={out.get('facts')}")
    except InvalidUpdateError as exc:
        print(f"  ❌ InvalidUpdateError：{str(exc).splitlines()[0][:78]}")
        print("  → 1.x 会当场拒绝，不会静默丢两条（这点比 0.x 好）")
        print("     但它只告诉你 'facts 只能收一个值'，不告诉你是哪个分支。")

    print("\n" + "=" * 78)
    print("④ 加 reducer 之后")
    print("=" * 78)
    out = build(WithReducer, worker_with_reducer).invoke({"task": "对比三家"})
    print(f"  facts = {out.get('facts')}")
    print(f"  条数 = {len(out.get('facts', []))}（期望 3）")


def main() -> None:
    asyncio.run(demo_asyncio())
    demo_langgraph()

    print("\n" + "=" * 78)
    print("结论：并发安全要「结构上就写不错」")
    print("=" * 78)
    print("  · 裸 dict：靠锁。能对，但每次改字段都要记得加锁——迟早有人忘。")
    print("  · 图框架：靠 reducer。**给字段声明合并规则**，写入方不需要知道还有谁在写。")
    print()
    print("  所以选 State 结构时，第一条判断是：")
    print("  **这个字段会不会被两个地方同时写？** 会 → 必须走框架的 reducer。")
    print()
    print("  这也是第 10 章存在的理由：State 不是'一个 dict'，")
    print("  它是**并发契约 + 生命周期契约 + 恢复契约**三者的合体。")


if __name__ == "__main__":
    main()
