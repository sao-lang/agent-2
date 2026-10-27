"""同一件事的框架写法：langchain 的 `bind_tools`。

对照，不是替代：框架接走了"schema 生成 → 请求编码 → 响应解析 → 消息对象"
这四段；执行、结果配对、错误回灌、去重仍然在调用方。

不联网：`ChatOpenAI` 换了一个 `httpx.MockTransport`（`scripted_chat`），
请求照常编码，响应来自脚本。**原理演示，不是模型实测**。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call
from tools import ORDER_TOOL, ORDERS, SYSTEM, TOOL_IMPL

SENT: list[dict] = []
CALLS = {"get_order": 0}


@tool
def get_order(order_id: Annotated[str, "订单号，例如 A1001"]) -> dict:
    """查询订单信息。返回 JSON，字段为 {"status": "已签收", "signed_days_ago": 3}。"""
    CALLS["get_order"] += 1
    if order_id not in ORDERS:
        raise KeyError(f"订单不存在：{order_id}")
    return ORDERS[order_id]


@tool
def get_order_bare(order_id: str) -> dict:
    """查询订单信息。返回 JSON，字段为 {"status": "已签收", "signed_days_ago": 3}。"""
    return ORDERS.get(order_id, {})


def respond(index: int, body: dict) -> dict:
    """第 1 次回一个动作；之后按回灌的订单状态给结论，读不出状态就明说。"""
    SENT.append(body)
    if index == 0:
        return chat_completion(
            content=None,
            tool_calls=[tool_call("get_order", {"order_id": "A1001"}, "call_order_01")],
            finish_reason="tool_calls", usage=(104, 17), model="demo-model")
    notes = [m for m in body["messages"] if m["role"] == "tool"]
    try:
        days = json.loads(notes[-1]["content"])["signed_days_ago"]
    except (IndexError, KeyError, json.JSONDecodeError):
        return chat_completion(content="工具结果里没有订单状态，我无法判断。",
                               finish_reason="stop", usage=(140, 14), model="demo-model")
    return chat_completion(content=f"可以退：已签收 {days} 天，在 7 天内。",
                           finish_reason="stop", usage=(138, 12), model="demo-model")


def main() -> None:
    model = scripted_chat(respond)
    bound = model.bind_tools([get_order])
    messages = [SystemMessage(SYSTEM), HumanMessage("订单 A1001 还能退吗？")]

    print("=== 一、`@tool` 从函数上读出来的定义 ===")
    print(f"  name        = {get_order.name}")
    print(f"  description = {get_order.description!r}")
    print(f"  args_schema = {get_order.args_schema.__name__}")
    print(f"  模型层 schema = {json.dumps(get_order.tool_call_schema.model_json_schema(), ensure_ascii=False)}")

    print()
    print("=== 二、编码进请求的 tools 字段（第 1 次请求）===")
    first = bound.invoke(messages)
    print(json.dumps(SENT[0]["tools"][0], ensure_ascii=False, indent=2))

    print()
    print("=== 三、解析回来的消息对象 ===")
    print(f"  类型        = {type(first).__name__}")
    print(f"  content     = {first.content!r}")
    print(f"  tool_calls  = {json.dumps(first.tool_calls, ensure_ascii=False)}")
    print(f"  args 的类型 = {type(first.tool_calls[0]['args']).__name__}")

    print()
    print("=== 四、手工执行，再回灌 ===")
    call = first.tool_calls[0]
    result = get_order.invoke(call["args"])
    tool_message = ToolMessage(content=json.dumps(result, ensure_ascii=False),
                               tool_call_id=call["id"])
    print(f"  工具返回值       = {result!r}")
    print(f"  ToolMessage 字段 = type={tool_message.type} "
          f"tool_call_id={tool_message.tool_call_id!r} content={tool_message.content!r}")

    final = bound.invoke([*messages, first, tool_message])
    print()
    print("=== 五、第 2 次响应 ===")
    print(f"  content    = {final.content!r}")
    print(f"  tool_calls = {final.tool_calls}")

    print()
    print("=== 六、框架没做的那一半 ===")
    loose = ToolMessage(content={"status": "已签收"}, tool_call_id="call_order_01")
    print(f"  content 传对象 → {type(loose.content).__name__} {loose.content!r}"
          f"   <- 不报错，但已经不是 JSON")
    wrong_id = ToolMessage(content="{}", tool_call_id="call_wrong")
    bound.invoke([*messages, first, wrong_id])
    sent = SENT[-1]["messages"]
    print(f"  tool_call_id 写错 → 本地无报错，发出去的是 {sent[-1]['tool_call_id']!r}")
    print(f"  assistant 里那条的 id 是 {sent[-2]['tool_calls'][0]['id']!r}")
    print(f"  请求发了 {len(SENT)} 次，工具被调用 {CALLS['get_order']} 次"
          f"   <- 那一次是上面手工 invoke 的，框架一次都没替你执行")

    print()
    print("=== 七、两份 schema 的差别 ===")
    from langchain_core.utils.function_calling import convert_to_openai_tool

    def encoded_parameters(t: object) -> dict:
        """框架最终编进请求的那份 parameters（与第三节看到的是同一个东西）。"""
        return convert_to_openai_tool(t)["function"]["parameters"]

    handwritten = len(json.dumps(ORDER_TOOL["function"]["parameters"], ensure_ascii=False))
    framed = len(json.dumps(SENT[0]["tools"][0]["function"]["parameters"], ensure_ascii=False))
    bare = len(json.dumps(encoded_parameters(get_order_bare), ensure_ascii=False))
    print(f"  手写版                    {handwritten} 字符")
    print(f"  框架版（有 Annotated）      {framed} 字符")
    print(f"  框架版（参数只有类型注解）   {bare} 字符")
    print(f"  手写版与框架版逐字段相同 = "
          f"{SENT[0]['tools'][0]['function']['parameters'] == ORDER_TOOL['function']['parameters']}")

    print()
    print("=== 八、另外两个参数编成了什么 ===")
    strict_bound = model.bind_tools([get_order], strict=True, parallel_tool_calls=False)
    strict_bound.invoke([HumanMessage("随便问一句")])
    body = {k: v for k, v in SENT[-1].items() if k != "messages"}
    print(json.dumps(body, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
