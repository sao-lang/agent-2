"""工具返回值的两段：`content` 给模型，`artifact` 留给程序。

第 6 章 4.2 讲的是"工具返回值写给谁看"：返回结论，模型就会把结论当依据；
返回全量记录，白占窗口。框架给了一个显式的位置来分开这两件事。

不联网：模型侧走 `scripted_chat`，原理演示，不是模型实测。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call

FULL_RECORD = {"status": "已签收", "signed_days_ago": 3,
               "items": [{"sku": "X1", "qty": 2}, {"sku": "X2", "qty": 1}],
               "audit": {"operator": "w_17", "at": "2025-06-02T09:14:00"}}


@tool("get_order", response_format="content_and_artifact")
def get_order(order_id: str) -> tuple[str, dict]:
    """查询订单状态。返回 JSON：{"status": ..., "signed_days_ago": ...}。"""
    summary = {"status": FULL_RECORD["status"], "signed_days_ago": FULL_RECORD["signed_days_ago"]}
    return json.dumps(summary, ensure_ascii=False), FULL_RECORD


def main() -> None:
    call = {"name": "get_order", "args": {"order_id": "A1001"}, "id": "call_a",
            "type": "tool_call"}
    message = get_order.invoke(call)
    print("=== 一、一条 ToolMessage 里的两段 ===")
    print(f"  type     = {type(message).__name__}")
    print(f"  content  = {message.content}")
    print(f"  artifact = {message.artifact}")
    print(f"  content 长度 = {len(message.content)} 字符，"
          f"artifact 长度 = {len(json.dumps(message.artifact, ensure_ascii=False))} 字符")

    sent: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        sent.append(body)
        if index == 0:
            return chat_completion(tool_calls=[tool_call("get_order", {"order_id": "A1001"},
                                                         "call_a")],
                                   finish_reason="tool_calls")
        return chat_completion(content="已签收 3 天，可以退。")

    create_agent(scripted_chat(respond), tools=[get_order]).invoke(
        {"messages": [HumanMessage("A1001 还能退吗？")]})

    print()
    print("=== 二、进请求的那条 tool 消息 ===")
    print(f"  {json.dumps(sent[1]['messages'][-1], ensure_ascii=False)}")
    print(f"  'items' 出现在请求里 = {'items' in json.dumps(sent[1], ensure_ascii=False)}")
    print(f"  'audit' 出现在请求里 = {'audit' in json.dumps(sent[1], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
