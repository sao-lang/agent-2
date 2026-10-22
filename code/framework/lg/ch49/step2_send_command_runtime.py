"""第 49 章 step2：Send（map-reduce）、Command（跳转+更新）、Runtime（上下文）（离线）。

运行：
    python code/framework/lg/ch49/step2_send_command_runtime.py

上一级的痛点：
    条件边只能"选一条路"。但真实需求经常是：
      · 一份文档拆成 5 段，5 段**同时**处理（map-reduce）
      · 一个节点执行完要**既跳转又改状态**
      · 同一张图要按"当前用户/租户"变化行为

这一级做什么：
    ① Send：动态扇出（fan-out），每条分支带着自己的输入
    ② Command：goto + update 一步完成，并用同一个 Command 做循环
    ③ Runtime：从 context 取运行时信息（不进 checkpoint、不进 prompt）
    ④ 一个坑：Send 的输入是**独立子状态**，不是父 state
"""
from __future__ import annotations

import operator
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, TypedDict

import operator as op

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

sys.path.insert(0, str(Path(__file__).parent))


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


class MapState(TypedDict):
    chunks: list[str]
    summaries: Annotated[list[str], op.add]


def fan_out(state: MapState) -> list[Send]:
    """一个节点返回多个 Send ⇒ 下游节点被并行调用 N 次。"""
    return [Send("summarize", {"chunk": c, "idx": i}) for i, c in enumerate(state["chunks"])]


class ChunkState(TypedDict):
    chunk: str
    idx: int


def summarize(state: dict) -> dict:
    return {"summaries": [f"[{state['idx']}] {state['chunk'][:12]}…"]}


class ReduceState(TypedDict):
    chunks: list[str]
    summaries: Annotated[list[str], op.add]


def main() -> None:
    line("① Send：把「一个输入」变成「N 个并行调用」")
    # 关键：Send 只能从**条件边**返回，不能从节点 return（节点只能返回 state 更新）。
    g = StateGraph(ReduceState)
    g.add_node("summarize", summarize)
    g.add_conditional_edges(START, fan_out, ["summarize"])
    g.add_edge("summarize", END)
    app = g.compile()

    chunks = ["退货政策：30 天内", "退款时效：7 个工作日", "运费险：质量问题才生效", "换货：先退回再寄出"]
    out = app.invoke({"chunks": chunks, "summaries": []})
    print(f"  {len(chunks)} 个块 → 得到 {len(out['summaries'])} 条摘要")
    for s in sorted(out["summaries"]):
        print(f"    {s}")
    print("\n  → Send 的第二个参数是一个**独立的小状态**，不是父 state（这是最常错的地方）")
    print("  → summaries 必须用 reducer 拼接，否则 N 条写回会冲突（第 48 章 ③）")

    line("② Command：一次返回，既跳转又改状态")
    class Cs(TypedDict):
        step: int
        log: Annotated[list[str], operator.add]

    def node_cmd(state: Cs):
        if state["step"] >= 2:
            return Command(goto=END, update={"log": ["done"]})
        return Command(goto="work", update={"step": state["step"] + 1, "log": [f"step {state['step']}"]})

    def work(_s: Cs) -> dict:
        return {"log": ["work"]}

    g2 = StateGraph(Cs)
    g2.add_node("cmd", node_cmd)
    g2.add_node("work", work)
    g2.add_edge(START, "cmd")
    g2.add_edge("work", "cmd")
    out2 = g2.compile().invoke({"step": 0, "log": []})
    print(f"  log = {out2['log']}")
    print(f"  step = {out2['step']}")
    print("\n  → Command 的价值：跳去哪、改什么，写在同一个返回值里。")
    print("    条件边只能选路，改状态还得另外 return —— 两件事拆在两地就容易写错。")

    line("③ Command(goto=[Send(...), ...]) 也能做动态扇出")
    print("  适用场景：你想在**同一步**里既决定分流、又改状态")

    line("④ Runtime：运行时的「当前请求」信息")
    @dataclass
    class Ctx:
        tenant: str
        debug: bool

    from langgraph.runtime import Runtime

    class Rs(TypedDict):
        answer: str

    def get_answer(state: Rs, runtime: Runtime[Ctx]) -> dict:  # noqa: ARG001
        c = runtime.context
        prefix = "[debug] " if c.debug else ""
        return {"answer": f"{prefix}租户 {c.tenant} 的答案"}

    g3 = StateGraph(Rs, context_schema=Ctx)
    g3.add_node("answer", get_answer)
    g3.add_edge(START, "answer")
    g3.add_edge("answer", END)
    app3 = g3.compile()
    print(f"  context=Ctx('acme', True) → {app3.invoke({'answer': ''}, context=Ctx('acme', True))}")
    print("\n  → context 不进 checkpoint、不进消息历史：它只活在这一次调用里")
    print("  → 别把租户 ID 塞进 State（会被持久化、会被模型看到）")

    line("⑤ 一个坑：Send 传的 dict 是子状态")
    print("  错误写法：Send('summarize', state)          → 整个父 state 被当成子状态")
    print("  正确写法：Send('summarize', {'chunk': c})   → 只传这条分支需要的字段")
    print("  为什么重要：子节点读不到多余字段，它返回的 dict 也只能写回 schema 里有的键。")


if __name__ == "__main__":
    main()
