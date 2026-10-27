"""第 9 章 9.3：四种消息与内容块。

运行：python code/knowledge/ch09_lc_basic/messages.py
脚本化后端：消息照常编码成真实请求，响应来自脚本。原理演示，不是模型实测。
"""

import json

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from scripted_chat import chat_completion, tool_call

SEEN = []


def make_llm(respond):
    """把 ChatOpenAI 接到 `respond(请求体) -> 响应字典` 上。"""

    def handler(request):
        body = json.loads(request.content)
        SEEN.append(body)
        return httpx.Response(200, json=respond(body))

    return ChatOpenAI(model="demo-model", api_key="sk-test",
                      http_client=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False))


def four_roles():
    """四种消息各自的 type 与用途。"""
    messages = [
        SystemMessage("你是退货政策助手，只回答与退货相关的问题。"),
        HumanMessage("订单 A1001 能退吗？"),
        AIMessage("请提供签收时间和商品状态。"),
        ToolMessage(content='{"status": "已签收"}', tool_call_id="call_demo"),
    ]
    for m in messages:
        print(f"{type(m).__name__:<14} type={m.type:<7} content={m.content!r}")


def text_vs_blocks():
    """同一条回复，content 与 content_blocks 两种读法。"""
    llm = make_llm(lambda body: chat_completion("签收后 7 天内可退。", usage=(24, 9)))
    reply = llm.invoke([HumanMessage("能退吗？")])
    print("content:", repr(reply.content))
    print("content_blocks:", reply.content_blocks)


def tool_call_message():
    """模型要动作时，正文是空的，动作在 tool_calls 里。"""
    llm = make_llm(lambda body: chat_completion(
        tool_calls=[tool_call("get_order", {"order_id": "A1001"})],
        finish_reason="tool_calls", usage=(40, 12)))
    reply = llm.invoke([HumanMessage("订单 A1001 什么时候到？")])
    print("content:", repr(reply.content))
    print("tool_calls:", reply.tool_calls)
    print("content_blocks:", reply.content_blocks)


def tool_message_round_trip():
    """把工具结果回灌，看请求体里多了什么。"""
    llm = make_llm(lambda body: chat_completion("订单已签收，不能退了。", usage=(60, 12)))
    call = AIMessage(content="", tool_calls=[
        {"name": "get_order", "args": {"order_id": "A1001"}, "id": "call_1", "type": "tool_call"}])
    result = ToolMessage(content='{"status": "已签收"}', tool_call_id="call_1")
    reply = llm.invoke([HumanMessage("订单 A1001 能退吗？"), call, result])
    print("回灌后的请求体 messages:")
    for m in SEEN[-1]["messages"]:
        print("  ", json.dumps(m, ensure_ascii=False))
    print("回复:", reply.content)


def blocks_are_normalized():
    """content 是原样，content_blocks 是归一化后的块。"""
    message = AIMessage(
        content=[{"type": "text", "text": "图里是一张签收单。"}],
        additional_kwargs={"reasoning_content": "先看表的行和列"},
    )
    print("content:", message.content)
    print("content_blocks:", message.content_blocks)


def role_is_gone():
    """1.x 的消息对象没有 `.role`，只有 `.type`。"""
    try:
        SystemMessage("你是退货政策助手。").role
    except AttributeError as e:
        print(f"AttributeError: {e}")


if __name__ == "__main__":
    print("== 四种消息 ==")
    four_roles()
    print()
    print("== role 属性 ==")
    role_is_gone()
    print()
    print("== 文本回复的两种读法 ==")
    text_vs_blocks()
    print()
    print("== 工具调用回复 ==")
    tool_call_message()
    print()
    print("== 工具结果回灌 ==")
    tool_message_round_trip()
    print()
    print("== 内容块的归一化 ==")
    blocks_are_normalized()
