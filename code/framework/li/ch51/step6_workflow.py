"""第 51 章 step6：LlamaIndex Workflow —— 事件驱动的流程编排（离线可跑）。

运行：
    python code/framework/li/ch51/step6_workflow.py

第 51 章只讲了「检索路线」（IngestionPipeline + QueryEngine）。
但 LlamaIndex 1.x 真正和 LangGraph 竞争的东西是 **Workflow**：

    LangGraph  ：节点 + 边 + State（显式图）
    Workflow   ：step + Event（事件驱动）

这一级用真实可运行的代码讲清三件事：

    ① Workflow 的心智模型（事件在 step 之间流动）
    ② 分支：一个 step 返回不同类型的事件 -> 走不同的下游 step
    ③ 三个必须知道的真实坑（都是我们撞过的）

全程不调模型，离线可复现。
"""
from __future__ import annotations

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 76


def line(t: str) -> None:
    print(f"\n{DPRINT}\n{t}\n{DPRINT}")


# ================================================================ ① 最小 Workflow
def demo_minimal() -> None:
    line("① 最小 Workflow：两个 step，一个事件")

    from llama_index.core.workflow import (
        Context,
        Event,
        StartEvent,
        StopEvent,
        Workflow,
        step,
    )

    class Ping(Event):
        n: int

    class W(Workflow):
        @step
        async def start(self, ctx: Context, ev: StartEvent) -> Ping:
            return Ping(n=ev.get("n", 1))

        @step
        async def work(self, ctx: Context, ev: Ping) -> StopEvent:
            return StopEvent(result=ev.n * 7)

    async def main() -> None:
        w = W(timeout=10)
        print(f"  run(n=6) -> {await w.run(n=6)}")

    asyncio.run(main())

    print()
    print("  三句话理解它：")
    print("    · `StartEvent` 是入口（就是 run() 的参数）")
    print("    · `StopEvent` 是出口（result 就是 run() 的返回值）")
    print("    · 中间的 step 之间靠**自定义 Event** 传递")


# ================================================================ ② 分支
def demo_branch() -> None:
    line("② 分支：一个 step 返回不同类型的事件，走不同的下游")

    from llama_index.core.workflow import (
        Context,
        Event,
        StartEvent,
        StopEvent,
        Workflow,
        step,
    )

    class NeedKB(Event):
        q: str

    class NeedCalc(Event):
        q: str

    class BranchResult(Event):
        value: str

    class W(Workflow):
        @step
        async def route(self, ctx: Context, ev: StartEvent) -> NeedKB | NeedCalc:
            q = ev.get("q", "")
            # ⚠️ ctx.store 是**异步**的，必须 await —— 这是坑 1
            await ctx.store.set("q", q)
            if any(c.isdigit() for c in q):
                return NeedCalc(q=q)
            return NeedKB(q=q)

        @step
        async def kb(self, ctx: Context, ev: NeedKB) -> BranchResult:
            return BranchResult(value=f"KB回答[{ev.q}]")

        @step
        async def calc(self, ctx: Context, ev: NeedCalc) -> BranchResult:
            return BranchResult(value=f"计算[{ev.q}]")

        @step
        async def collect(self, ctx: Context, ev: BranchResult) -> StopEvent:
            q = await ctx.store.get("q")
            return StopEvent(result={"answer": ev.value, "q": q})

    async def main() -> None:
        print(f"  无数字: {await W(timeout=10).run(q='退款要多久')}")
        print(f"  有数字: {await W(timeout=10).run(q='退款 399 元多久到')}")

    asyncio.run(main())

    print()
    print("  ---- 和 LangGraph 的关键差异：")
    rows = [
        ("怎么分流", "返回不同类型的事件", "返回 Command(goto=...) 或条件边"),
        ("下游怎么知道接谁", "按**事件类型**自动匹配", "按**节点名**显式指定"),
        ("状态存在哪", "`ctx.store`（键值）+ 事件字段", "State（TypedDict，有 reducer）"),
        ("并行扇出", "`ctx.send_event` + `collect_events`", "`Send`（第 49 章）"),
        ("可视化", "没有内置图", "`get_graph().draw_mermaid()`"),
    ]
    print(f"  {'维度':<18} {'LlamaIndex Workflow':<32} LangGraph")
    print(f"  {'-' * 18} {'-' * 32} {'-' * 30}")
    for a, b, c in rows:
        print(f"  {a:<18} {b:<32} {c}")


# ================================================================ ③ 三个坑
def demo_pitfalls() -> None:
    line("③ 三个真实坑（我们都撞过）")

    print("  坑 1：`ctx.store` 是**异步**的")
    print()
    print("    ❌  ctx.store.set('q', q)          -> RuntimeWarning: never awaited")
    print("        ctx.store.get('q')            -> 返回 <coroutine object>")
    print("    ✅  await ctx.store.set('q', q)")
    print("        await ctx.store.get('q')")
    print()
    print("    这个坑特别隐蔽：**不报错，只是拿到一个 coroutine 对象**。")
    print("    你会看到 q 字段变成 <coroutine object StateStoreFacade.get at 0x...>。")
    print()

    print("  坑 2：事件类**不能**用 `@dataclass`")
    print()
    print("    ❌  @dataclass")
    print("        class One(Event):")
    print("            item: str")
    print("        -> RecursionError: maximum recursion depth exceeded")
    print()
    print("    ✅  class One(Event):")
    print("            item: str")
    print()
    print("    为什么：`Event` 本身是 Pydantic 模型，再叠 @dataclass 会让")
    print("    属性访问在 `__getattr__` 里无限递归。")
    print()
    print("    ⚠️ 顺带一个坑：字段名不能叫 `items`（会 shadow 父类的同名属性）")
    print("       运行会给出 UserWarning。改成 `values` / `ids` 之类。")
    print()

    print("  坑 3：step 的返回值决定「下游谁来接」")
    print()
    print("    · 返回 `StopEvent(result=...)`  -> 流程结束")
    print("    · 返回某个 Event 实例          -> 该事件类型的 step 会收到")
    print("    · 返回 `None`                  -> 本步骤结束，但流程继续（用于只发副作用）")
    print("    · 返回 `list[Event]`           -> 并发触发多个下游")
    print()
    print("    最容易错的是「忘了 return」—— 那样流程会静默停住，" )
    print("    既不报错也不返回结果，直到 timeout。")


# ================================================================ ④ 选型
def demo_when_to_use() -> None:
    line("④ 什么时候用 Workflow，什么时候用 LangGraph")

    print("  两者的抽象不同，但能力高度重叠。选型看三件事：")
    print()
    rows = [
        ("你的系统已经用 LlamaIndex 做检索", "Workflow", "同一个库，不用装两套"),
        ("需要「中断 + 人工审批 + 恢复」", "LangGraph", "checkpointer + interrupt 是成熟方案"),
        ("需要「把图画出来给老板看」", "LangGraph", "内置 mermaid 导出"),
        ("流程是「事件驱动、类型安全」的", "Workflow", "按事件类型路由，比节点名更类型化"),
        ("需要跨 session 的长期记忆", "LangGraph（store）或 LlamaIndex（memory）", "两者都有，看生态"),
    ]
    print(f"  {'情况':<34} {'选':<14} 理由")
    print(f"  {'-' * 34} {'-' * 14} {'-' * 26}")
    for a, b, c in rows:
        print(f"  {a:<34} {b:<14} {c}")

    print()
    print("  ---- 一个实务建议：")
    print("     **不要为了「统一技术栈」而把两个框架拼在一起。**")
    print("     如果检索已经在 LlamaIndex 里，就用它的 Workflow；")
    print("     如果核心是有状态的长流程，就用 LangGraph，检索只当工具。")
    print("     混用两套状态管理是最容易出事的地方（第 23 章讲过 State 的坑）。")


if __name__ == "__main__":
    demo_minimal()
    demo_branch()
    demo_pitfalls()
    demo_when_to_use()
    print()
    print(DPRINT)
    print("step6 完成。四句话带走：")
    print("  1. Workflow 的心智模型是「事件在 step 之间流动」，不是「节点 + 边」。")
    print("  2. 分流靠「返回不同类型的事件」，下游按事件类型自动匹配。")
    print("  3. ctx.store 必须 await；事件类不能用 @dataclass；忘了 return 会静默停住。")
    print("  4. 和 LangGraph 能力重叠，按「中断持久化 / 可视化 / 生态」选，别硬拼。")
    print(DPRINT)
