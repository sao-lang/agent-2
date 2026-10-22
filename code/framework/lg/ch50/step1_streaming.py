"""第 50 章 step1：stream_mode 的全部取值（离线）。

运行：
    python code/framework/lg/ch50/step1_streaming.py

上一级的痛点：
    Agent 跑 8 秒，用户盯 8 秒白屏。你得把"正在进行什么"流出去。
    但一次运行里可流的东西有五六种，选错了前端就没法用。

这一级做什么：
    ① 逐个跑 stream_mode 的每个取值，看它到底吐出什么形状
    ② 组合模式（updates + messages）—— 生产环境最常用
    ③ 一个坑：messages 模式下会同时吐"模型 token"和"工具结果"

对照你的前端需求：
    想打字机效果            → messages
    想显示"正在调用工具"     → updates
    想看完整状态快照        → values
    想调试                  → debug
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lc"))

from _fake import ai, scripted, text_of  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


@tool
def query_order(order_id: str) -> str:
    """查订单状态"""
    return f"{order_id}: 在保修期内"


class S(TypedDict):
    messages: Annotated[list, add_messages]


def build():
    model = scripted(
        ai(tool_calls=[{"name": "query_order", "args": {"order_id": "A1"}}]),
        ai("在保修期内，可以免费修。"),
    )

    def call_model(state: S) -> dict:
        return {"messages": [model.invoke(state["messages"])]}

    g = StateGraph(S)
    g.add_node("model", call_model)
    g.add_node("tools", ToolNode([query_order]))
    g.add_edge(START, "model")
    g.add_conditional_edges("model", tools_condition)
    g.add_edge("tools", "model")
    return g.compile()


INP = {"messages": [HumanMessage("A1 还能保吗")]}


def main() -> None:
    modes = ["values", "updates", "messages", "debug", "custom"]
    line("① 逐个 stream_mode 看形状")
    for mode in modes:
        app = build()
        print(f"\n  ── stream_mode={mode!r} ──")
        try:
            for i, chunk in enumerate(app.stream(INP, stream_mode=mode), 1):
                if i > 4:
                    print("    ...（省略）")
                    break
                if mode == "messages":
                    msg, meta = chunk
                    print(f"    {i}. [{meta.get('langgraph_node')}] {text_of(msg)!r}")
                elif mode == "values":
                    print(f"    {i}. messages={len(chunk['messages'])} 条")
                elif mode == "updates":
                    print(f"    {i}. {list(chunk)}")
                elif mode == "debug":
                    print(f"    {i}. type={chunk.get('type')} step={chunk.get('step')}")
                else:
                    print(f"    {i}. {chunk!r}")
        except Exception as e:  # noqa: BLE001
            print(f"    （{mode} 需要额外配合：{type(e).__name__}）")

    line("② 组合模式：updates + messages（生产最常用）")
    app = build()
    for mode, chunk in app.stream(INP, stream_mode=["updates", "messages"]):
        if mode == "messages":
            msg, meta = chunk
            print(f"    [token] {meta.get('langgraph_node')}: {text_of(msg)!r}")
        else:
            print(f"    [event] {list(chunk)}")
    print("\n  → 前端：token 进打字机，event 进「正在调用 query_order…」的状态条")

    line("③ 一个坑：messages 模式会把工具结果也当成「消息」吐出")
    print("  你会收到三种：")
    print("    AIMessageChunk（模型的 token） → 追加到气泡")
    print("    AIMessage（含 tool_calls）      → 显示「正在调用…」，不要当文本")
    print("    ToolMessage                     → 不要给用户看（或转成「查到了」）")
    print("  判断依据：看 chunk[1]['langgraph_node'] 和消息类型，不要一律拼字符串。")

    line("④ 其余三种模式速查")
    print("""
  values     每一轮结束的**完整 state**（最新快照），适合「渲染整页」
  updates    每一轮**哪个节点改了什么**，适合「进度条 / 事件流」
  custom     节点里用 get_stream_writer() 自己推任意事件（进度百分比等）
  debug      每个 task 的开始/结束/结果，适合本地排查
  messages   模型 token 流 + 元数据（2 元组 (message_chunk, metadata)）
  """)

    line("⑤ 后端怎么接：SSE 三行伪代码")
    print("""
  async def chat(req):
      async for mode, chunk in app.astream(req.input, stream_mode=["updates", "messages"]):
          yield sse({"kind": mode, "data": serialize(chunk)})
    """)


if __name__ == "__main__":
    main()
