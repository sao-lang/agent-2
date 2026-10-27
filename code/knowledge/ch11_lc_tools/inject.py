"""注入：`InjectedState`、`InjectedStore`、`InjectedToolCallId`、`ToolRuntime`。

这些参数不来自模型，来自执行环境。它们**不进请求体**——模型的 `parameters`
里没有它们，模型也就无从填写。

从 1.4.7 起四者的导入位置都在 `langchain.tools`（底层在 `langgraph.prebuilt`）。

不联网：模型侧走 `scripted_chat`，原理演示，不是模型实测。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict

from langchain.agents import create_agent
from langchain.tools import (InjectedState, InjectedStore, InjectedToolCallId,
                             ToolRuntime)
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langgraph.store.memory import InMemoryStore

from scripted_chat import chat_completion, scripted_chat, tool_call

SENT: list[dict] = []


class AppState(TypedDict, total=False):
    """agent 的 state。`user_id` 由调用方放进 invoke 的入参，模型改不了。"""

    user_id: str
    messages: Annotated[list[AnyMessage], add_messages]


@tool("get_my_order")
def get_my_order(order_id: str, state: Annotated[dict, InjectedState]) -> str:
    """查询当前用户自己的订单。用户身份由 state 提供，模型不需要也不应该填。"""
    return json.dumps({"user_id": state.get("user_id"), "order_id": order_id,
                       "status": "已签收"}, ensure_ascii=False)


@tool("who_am_i")
def who_am_i(runtime: ToolRuntime) -> str:
    """返回本次执行拿到的 state、tool_call_id 与可用工具名。"""
    return json.dumps({"user_id": runtime.state.get("user_id"),
                       "tool_call_id": runtime.tool_call_id,
                       "tools": [t.name for t in runtime.tools]}, ensure_ascii=False)


@tool("bump_counter")
def bump_counter(key: str, store: Annotated[Any, InjectedStore]) -> str:
    """把一个计数加一。计数存在 store 里，模型不需要也不应该提供 store。"""
    item = store.get(("counters",), key)
    n = (item.value["n"] if item else 0) + 1
    store.put(("counters",), key, {"n": n})
    return json.dumps({"key": key, "n": n}, ensure_ascii=False)


@tool("mark_handled")
def mark_handled(order_id: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
    """返回这次调用自己的 id。要自己造幂等键时，从它派生。"""
    return json.dumps({"order_id": order_id, "tool_call_id": tool_call_id}, ensure_ascii=False)


def respond(index: int, body: dict) -> dict:
    SENT.append(body)
    if index == 0:
        return chat_completion(
            tool_calls=[tool_call("get_my_order", {"order_id": "A1001"}, "call_a"),
                        tool_call("who_am_i", {}, "call_b"),
                        tool_call("bump_counter", {"key": "refund"}, "call_c"),
                        tool_call("bump_counter", {"key": "refund"}, "call_d"),
                        tool_call("mark_handled", {"order_id": "A1001"}, "call_e")],
            finish_reason="tool_calls")
    return chat_completion(content="查到了。")


def main() -> None:
    store = InMemoryStore()
    agent = create_agent(scripted_chat(respond),
                         tools=[get_my_order, who_am_i, bump_counter, mark_handled],
                         state_schema=AppState, store=store)
    out = agent.invoke({"messages": [HumanMessage("我的订单 A1001 什么状态？")],
                        "user_id": "u_42"})

    print("=== 一、进请求的 parameters 里没有注入参数 ===")
    for item in SENT[0]["tools"]:
        print(f"  {item['function']['name']:14} "
              f"parameters={json.dumps(item['function']['parameters'], ensure_ascii=False)}")

    print()
    print("=== 二、执行时拿到的注入值 ===")
    for msg in out["messages"]:
        if type(msg).__name__ == "ToolMessage":
            print(f"  {msg.tool_call_id:8} {msg.content}")

    print()
    print(f"=== 三、store 里留下的计数 === {store.get(('counters',), 'refund').value}")
    print(f"=== 四、state 的键（模型没有写进去的能力）=== {sorted(k for k in out if k != 'messages')}")


if __name__ == "__main__":
    main()
