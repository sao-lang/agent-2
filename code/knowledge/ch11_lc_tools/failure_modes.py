"""第 9 节的两种坏法，各自跑一遍：注入标记漏写、工具重名。

两种都不报错。这是它们危险的地方——请求照发、工具照调、答案照出。

不联网：模型侧走 `scripted_chat`，原理演示，不是模型实测。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call


def missing_marker() -> None:
    """`user_id` 忘了加 `Annotated[..., InjectedState]`，它就变成普通参数。"""

    @tool("get_my_order")
    def get_my_order(order_id: str, user_id: str) -> str:
        """查询订单。"""
        return json.dumps({"user_id": user_id, "order_id": order_id}, ensure_ascii=False)

    sent: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        sent.append(body)
        if index == 0:
            return chat_completion(
                tool_calls=[tool_call("get_my_order",
                                      {"order_id": "A1001", "user_id": "u_88"}, "call_a")],
                finish_reason="tool_calls")
        return chat_completion(content="查到了。")

    out = create_agent(scripted_chat(respond), tools=[get_my_order]).invoke(
        {"messages": [HumanMessage("我的订单 A1001 什么状态？")]})
    print(f"  进请求的 parameters = "
          f"{json.dumps(sent[0]['tools'][0]['function']['parameters'], ensure_ascii=False)}")
    for msg in out["messages"]:
        if type(msg).__name__ == "ToolMessage":
            print(f"  工具收到的内容 = {msg.content}")
    print("  报错 = 无")


def duplicate_name() -> None:
    """两个工具同名：后一个覆盖前一个，没有提示。"""

    @tool("get_order")
    def billing_order(order_id: str) -> str:
        """账务系统的订单查询。"""
        return json.dumps({"source": "billing"}, ensure_ascii=False)

    @tool("get_order")
    def warehouse_order(order_id: str) -> str:
        """仓储系统的订单查询。"""
        return json.dumps({"source": "warehouse"}, ensure_ascii=False)

    sent: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        sent.append(body)
        if index == 0:
            return chat_completion(
                tool_calls=[tool_call("get_order", {"order_id": "A1001"}, "call_a")],
                finish_reason="tool_calls")
        return chat_completion(content="查到了。")

    out = create_agent(scripted_chat(respond),
                       tools=[billing_order, warehouse_order]).invoke(
        {"messages": [HumanMessage("订单 A1001 什么状态？")]})
    names = [(t["function"]["name"], t["function"]["description"]) for t in sent[0]["tools"]]
    print(f"  进请求的工具 = {names}")
    for msg in out["messages"]:
        if type(msg).__name__ == "ToolMessage":
            print(f"  实际执行的是 = {msg.content}")
    print("  报错 = 无")


def main() -> None:
    print("=== 一、注入标记漏写 ===")
    missing_marker()
    print()
    print("=== 二、两个工具同名 ===")
    duplicate_name()


if __name__ == "__main__":
    main()
