"""一次完整的工具调用往返，全程走真实 `openai` SDK。

请求带 `tools` → 返回 `tool_calls` → 手工执行 → 以 `role="tool"` 回灌 → 第二次拿到答案。
不联网：服务端是 `fake_server` 的脚本化实现，**响应文本与 usage 都是写死的**，
只用来固定 JSON 形状（原理演示，不是模型实测）。

换成真实服务时，把 `client_for(base_url)` 换成
`OpenAI(api_key=..., base_url=...)`，其余代码不动。
"""

from __future__ import annotations

import json

from fake_server import chat_completion, client_for, scripted_server
from tools import ORDER_TOOL, SYSTEM, TOOL_IMPL, tool_call

MODEL = "demo-model-2024"

SENT: list[dict] = []


def respond(index: int, body: dict) -> dict:
    """第 1 次回一个动作；第 2 次按回灌的订单状态给结论。"""
    SENT.append(body)
    if index == 0:
        return chat_completion(
            content=None,
            tool_calls=[tool_call("get_order", {"order_id": "A1001"}, "call_order_01")],
            finish_reason="tool_calls",
            usage=(104, 17),
            model=MODEL,
        )
    order = json.loads([m for m in body["messages"] if m["role"] == "tool"][-1]["content"])
    days = order["signed_days_ago"]
    verdict = "可以退" if days <= 7 else "不可以退"
    return chat_completion(
        content=f"{verdict}：已签收 {days} 天，{'在 7 天内' if days <= 7 else '超过 7 天'}。",
        finish_reason="stop",
        usage=(138, 12),
        model=MODEL,
    )


def execute(call) -> dict:
    """执行一个 tool_call，返回一条 tool 消息。

    三点必须对上：role 是 tool、tool_call_id 与 id 一致、content 是字符串。
    """
    name = call.function.name
    try:
        args = json.loads(call.function.arguments)
    except json.JSONDecodeError as e:
        return {"role": "tool", "tool_call_id": call.id,
                "content": json.dumps({"error": f"参数不是合法 JSON：{e}"}, ensure_ascii=False)}

    if name not in TOOL_IMPL:
        # 模型可以编出一个没声明过的名字。报错也走 tool 消息，不要抛给上层。
        return {"role": "tool", "tool_call_id": call.id,
                "content": json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)}

    try:
        result = TOOL_IMPL[name](**args)
    except Exception as e:  # 工具自己的失败也要让模型知道
        return {"role": "tool", "tool_call_id": call.id,
                "content": json.dumps({"error": str(e)}, ensure_ascii=False)}

    return {"role": "tool", "tool_call_id": call.id,
            "content": json.dumps(result, ensure_ascii=False)}


def main() -> None:
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "订单 A1001 还能退吗？"},
    ]

    with scripted_server(respond) as base_url:
        client = client_for(base_url)

        print("=== 第 1 次请求：服务端收到的原文 ===")
        # 先发一次，请求体在 respond 里被记下来，这里只打前 2 条 messages 与 tools
        resp1 = client.chat.completions.create(
            model=MODEL, messages=messages, tools=[ORDER_TOOL])
        print(f"messages 条数 = {len(SENT[0]['messages'])}")
        print("tools[0] =", json.dumps(SENT[0]["tools"][0], ensure_ascii=False, indent=2))

        print()
        print("=== 第 1 次响应：resp.model_dump() ===")
        print(json.dumps(resp1.model_dump(), ensure_ascii=False, indent=2))

        print()
        print("=== 这一条 message 的 tool_calls ===")
        message = resp1.choices[0].message
        print(f"类型 = {type(message).__name__}")
        for call in message.tool_calls or []:
            print(f"id={call.id}  type={call.type}  name={call.function.name}")
            print(f"arguments={call.function.arguments!r}"
                  f"  类型={type(call.function.arguments).__name__}")

        print()
        print("=== 执行并回灌 ===")
        # 原样保留 assistant 消息：arguments 那串文字是模型当初生成的那一份
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls or []:
            tool_message = execute(call)
            messages.append(tool_message)
            print(json.dumps(tool_message, ensure_ascii=False))

        print()
        print("=== 第 2 次请求：messages 末尾两条 ===")
        resp2 = client.chat.completions.create(
            model=MODEL, messages=messages, tools=[ORDER_TOOL])
        print(json.dumps(SENT[1]["messages"][-2:], ensure_ascii=False, indent=2))

        print()
        print("=== 第 2 次响应：这一次才有答案 ===")
        print(f"finish_reason = {resp2.choices[0].finish_reason}")
        print(f"content = {resp2.choices[0].message.content!r}")

        print()
        print("=== 两次请求的 token 账 ===")
        total = 0
        for i, resp in enumerate((resp1, resp2), 1):
            usage = resp.usage
            total += usage.total_tokens
            print(f"  第 {i} 次：prompt={usage.prompt_tokens}  "
                  f"completion={usage.completion_tokens}  total={usage.total_tokens}")
        print(f"  合计 {total} tokens，共 2 次请求")

        print()
        print("=== messages 的增长 ===")
        print(f"  请求 1 的 messages 条数：{len(SENT[0]['messages'])}")
        print(f"  请求 2 的 messages 条数：{len(SENT[1]['messages'])}")
        print(f"  多出来的 role：{[m['role'] for m in SENT[1]['messages'][len(SENT[0]['messages']):]]}")

        print()
        print("=== 响应对象上能读到的其余字段 ===")
        print(f"  id={resp1.id}  model={resp1.model}  object={resp1.object}")


if __name__ == "__main__":
    main()
