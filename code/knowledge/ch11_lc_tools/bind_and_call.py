"""绑定与调用：`bind_tools` 把工具定义编进请求，回来的是带 id 的 tool_calls。

这一节对照第 6 章的手写往返：手写版里"schema 编码、响应解析、消息对象、
按 id 配对"四段都要自己写；框架接走了这四段，执行仍然留在调用方。

不联网：`ChatOpenAI` 换了一个 `httpx.MockTransport`（`scripted_chat`），
请求照常编码，响应来自脚本。**原理演示，不是模型实测**。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool

from scripted_chat import chat_completion, scripted_chat, tool_call

SENT: list[dict] = []


@tool("get_order")
def get_order(order_id: str) -> str:
    """查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。"""
    time.sleep(0.2)
    return json.dumps({"status": "已签收", "signed_days_ago": 3}, ensure_ascii=False)


@tool("get_weather")
def get_weather(city: str) -> str:
    """查询城市天气。返回 JSON：{"temp": 24, "unit": "c"}。"""
    time.sleep(0.2)
    return json.dumps({"temp": 24, "unit": "c"}, ensure_ascii=False)


TOOLS = [get_order, get_weather]


def one_shot(choice: object) -> None:
    """只关心请求体：`tool_choice` 的各种取值编成什么。`None` 表示不传。"""

    def respond(index: int, body: dict) -> dict:
        SENT.append(body)
        return chat_completion(content="好的，")

    model = scripted_chat(respond)
    if choice is None:
        model.bind_tools(TOOLS).invoke([HumanMessage("A1001 还能退吗？")])
    else:
        model.bind_tools(TOOLS, tool_choice=choice).invoke([HumanMessage("A1001 还能退吗？")])
    wire = SENT[-1]
    encoded = json.dumps(wire["tool_choice"], ensure_ascii=False) if "tool_choice" in wire else "（请求体里没有这个键）"
    print(f"  tool_choice={choice!r:16} -> {encoded}")


def two_rounds() -> None:
    """一次响应给三个调用，逐个执行再回灌。"""

    def respond(index: int, body: dict) -> dict:
        SENT.append(body)
        if index == 0:
            return chat_completion(
                content=None,
                tool_calls=[tool_call("get_order", {"order_id": "A1001"}, "call_a"),
                            tool_call("get_order", {"order_id": "A1002"}, "call_b"),
                            tool_call("get_weather", {"city": "杭州"}, "call_c")],
                finish_reason="tool_calls", usage=(104, 48))
        return chat_completion(content="A1001 可以退；A1002 签收 3 天，也可以退。",
                               finish_reason="stop", usage=(212, 21))

    model = scripted_chat(respond)
    bound = model.bind_tools(TOOLS, tool_choice="auto")
    messages = [SystemMessage("你是一个只处理退货问题的客服助手。"),
                HumanMessage("订单 A1001 和 A1002 还能退吗？现在杭州天气如何？")]

    first = bound.invoke(messages)
    print(f"  第 1 次响应的 content = {first.content!r}")
    print(f"  一次给出 {len(first.tool_calls)} 个调用：")
    for call in first.tool_calls:
        print(f"    id={call['id']:8} name={call['name']:12} args={call['args']}")
    print(f"  args 已经是对象，不是 JSON 字符串 = {type(first.tool_calls[0]['args']).__name__}")

    results, elapsed = execute_all(first, TOOLS)

    print()
    print("  逐个执行，拿回的是 ToolMessage：")
    for msg in results:
        print(f"    tool_call_id={msg.tool_call_id:8} status={msg.status:8} content={msg.content}")
    print(f"  3 次调用各睡 0.2 秒，总耗时 {elapsed:.2f} 秒"
          f"  <- 顺序执行，不是并发")

    second = bound.invoke([*messages, first, *results])
    print()
    print(f"  第 2 次请求的 messages 条数 = {len(SENT[-1]['messages'])}")
    print(f"  其中 role 依次为 = {[m['role'] for m in SENT[-1]['messages']]}")
    print(f"  第 2 次响应的 content = {second.content!r}")
    print(f"  两次的 usage = {first.usage_metadata['total_tokens']} + "
          f"{second.usage_metadata['total_tokens']} = "
          f"{first.usage_metadata['total_tokens'] + second.usage_metadata['total_tokens']} tokens")


def execute_all(first: object, tools: list[BaseTool]) -> tuple[list[ToolMessage], float]:
    """把一条响应要的调用逐个执行。返回 (ToolMessage 列表, 执行耗时)。"""
    by_name: dict[str, BaseTool] = {t.name: t for t in tools}
    started = time.perf_counter()
    results: list[ToolMessage] = [by_name[call["name"]].invoke(call) for call in first.tool_calls]
    elapsed = time.perf_counter() - started
    return results, elapsed


def extras() -> None:
    """`bind_tools` 的另外两个参数编进请求体的位置不一样。"""

    def respond(index: int, body: dict) -> dict:
        SENT.append(body)
        return chat_completion(content="好的，")

    for label, kwargs in [("不传", {}),
                          ("strict=True", {"strict": True}),
                          ("parallel_tool_calls=False", {"parallel_tool_calls": False})]:
        scripted_chat(respond).bind_tools([get_order], **kwargs).invoke([HumanMessage("查 A1001")])
        wire = SENT[-1]
        top = {k: wire[k] for k in ("strict", "parallel_tool_calls") if k in wire}
        fn_keys = sorted(wire["tools"][0]["function"])
        print(f"  {label:28} 顶层键={top or '无'}  function 的键={fn_keys}")


def tool_node_alone() -> None:
    """`ToolNode` 要挂在图上才能跑：单独调拿到的是运行时缺配置。"""
    from langgraph.prebuilt import ToolNode

    node = ToolNode(TOOLS)
    call = {"name": "get_order", "args": {"order_id": "A1001"}, "id": "call_a",
            "type": "tool_call"}
    message = AIMessage(content="", tool_calls=[call])
    try:
        node.invoke({"messages": [message]})
    except Exception as exc:
        print(f"  ToolNode 单独 invoke -> {type(exc).__name__}: {exc}")


def legacy_dict() -> None:
    """第 6 章那种手写字典也能直接交给 `bind_tools`，一个字段不用改。"""
    legacy = {"type": "function",
              "function": {"name": "get_order", "description": "查询订单状态。",
                           "parameters": {"type": "object",
                                          "properties": {"order_id": {"type": "string",
                                                                     "description": "订单号"}},
                                          "required": ["order_id"]}}}

    def respond(index: int, body: dict) -> dict:
        SENT.append(body)
        return chat_completion(content="好的，")

    scripted_chat(respond).bind_tools([legacy]).invoke([HumanMessage("查 A1001")])
    print(f"  OK tools: {json.dumps(SENT[-1]['tools'], ensure_ascii=False)}")


def main() -> None:
    print("=== 一、tool_choice 的各种取值编进请求的样子 ===")
    for choice in (None, "auto", "none", "required", "any", "get_order"):
        one_shot(choice)

    print()
    print("=== 二、strict 与 parallel_tool_calls 的位置 ===")
    extras()

    print()
    print("=== 三、一次响应里的三个调用 ===")
    two_rounds()

    print()
    print("=== 四、ToolNode 单独调 ===")
    tool_node_alone()

    print()
    print("=== 五、手写字典直接传 ===")
    legacy_dict()


if __name__ == "__main__":
    main()
