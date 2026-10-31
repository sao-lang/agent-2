"""LangGraph 的五种 stream_mode，以及 astream_events 的事件流。

不联网。模型是 FakeListChatModel，按字符吐出"你好，世界"。
每个模式只打印它独有的一部分，避免输出过长。

运行：python code/knowledge/ch37_langgraph_persist/stream_modes.py
"""

from __future__ import annotations

import asyncio
import operator
from collections import Counter
from typing import Annotated, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    topic: str
    answer: str
    log: Annotated[list[str], operator.add]


MODEL = FakeListChatModel(responses=["你好，世界"])


def think(state: State) -> dict:
    writer = get_stream_writer()
    writer({"stage": "thinking", "topic": state["topic"]})
    return {"log": ["think"]}


def chat(state: State) -> dict:
    msg = MODEL.invoke([("user", state["topic"])])
    return {"answer": msg.content, "log": ["chat"]}


def build():
    g = StateGraph(State)
    g.add_node("think", think)
    g.add_node("chat", chat)
    g.add_edge(START, "think")
    g.add_edge("think", "chat")
    g.add_edge("chat", END)
    return g.compile()


INPUT = {"topic": "打个招呼", "answer": "", "log": []}


def main() -> None:
    app = build()

    print("=== 1. values：每一步的完整状态 ===")
    for snap in app.stream(INPUT, stream_mode="values"):
        print(f"  log={snap['log']} answer={snap['answer']!r}")
    print()

    print("=== 2. updates：这一步哪个节点改了什么 ===")
    for chunk in app.stream(INPUT, stream_mode="updates"):
        print(f"  {chunk}")
    print()

    print("=== 3. custom：节点自己写的进度 ===")
    for chunk in app.stream(INPUT, stream_mode="custom"):
        print(f"  {chunk}")
    print()

    print("=== 4. messages：模型吐出的 token ===")
    per_node: dict[str, list[str]] = {}
    for msg, meta in app.stream(INPUT, stream_mode="messages"):
        per_node.setdefault(meta["langgraph_node"], []).append(msg.content)
    for node, pieces in per_node.items():
        print(f"  {node}: {len(pieces)} 片 -> {''.join(pieces)!r}")
    print()

    print("=== 5. debug：框架内部事件计数 ===")
    kinds = Counter(ev["type"] for ev in app.stream(INPUT, stream_mode="debug"))
    print(f"  {dict(kinds)}")
    print()

    print("=== 6. astream_events v2：跨组件的事件流 ===")

    async def collect() -> None:
        events = []
        async for ev in app.astream_events(INPUT, version="v2"):
            events.append((ev["event"], ev.get("name")))
        counts = Counter(e for e, _ in events)
        print(f"  事件数={len(events)} 类型={dict(counts)}")
        for event, name in events:
            if event in ("on_chain_start", "on_chain_end",
                         "on_chat_model_start", "on_chat_model_end"):
                print(f"    {event:<24}{name}")

    asyncio.run(collect())
    print()
    print("  <- messages 模式只给 token；astream_events 带层级与组件名，")
    print("     适合把一次运行还原成 span 树，见第 38 章的跨 agent trace")


if __name__ == "__main__":
    main()
