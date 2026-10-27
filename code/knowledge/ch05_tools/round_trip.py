"""一次完整的工具调用往返：请求带 tools -> 返回 tool_calls -> 手工执行 -> 回灌 -> 第二次回答。

不联网。服务端是 transport.respond 的脚本化实现，响应体按 OpenAI 兼容格式构造，
用来固定 JSON 形状；不是真实模型的输出。
"""

from __future__ import annotations

import json

from transport import ORDER_TOOL, SYSTEM, Transport

# ---------------------------------------------------------------- 工具实现

# 订单表：真实系统里这在数据库里，这里用一个字面量代替。
ORDERS = {
    "A1001": {"status": "已签收", "signed_days_ago": 3},
    "A1002": {"status": "已签收", "signed_days_ago": 40},
}


def get_order(order_id: str) -> dict:
    """模型让做什么，调用方就做什么。返回值是 Python 对象，回灌前要变成字符串。"""
    if order_id not in ORDERS:
        raise KeyError(f"订单不存在：{order_id}")
    return ORDERS[order_id]


TOOL_IMPL = {"get_order": get_order}


# ---------------------------------------------------------------- 回灌

def execute(call: dict) -> dict:
    """执行一个 tool_call，返回一条 tool 消息。

    三点必须对上：role 是 tool、带 tool_call_id、content 是字符串。
    """
    fn = call["function"]
    name = fn["name"]
    try:
        args = json.loads(fn["arguments"])
    except json.JSONDecodeError as e:
        return {
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({"error": f"参数不是合法 JSON：{e}"}, ensure_ascii=False),
        }

    if name not in TOOL_IMPL:
        # 模型可以编出一个不存在的工具名。报错也走 tool 消息，不要抛给上层。
        return {
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False),
        }

    try:
        result = TOOL_IMPL[name](**args)
    except Exception as e:  # 工具自己的失败也要让模型知道
        return {
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({"error": str(e)}, ensure_ascii=False),
        }

    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "content": json.dumps(result, ensure_ascii=False),
    }


# ---------------------------------------------------------------- 一次往返

def one_round(request: dict, transport: Transport) -> tuple[str, list[dict]]:
    """发请求、执行所有 tool_calls、把结果回灌进 messages。

    返回 (finish_reason, 新增的 messages)。注意这里**没有循环**：
    调用方拿到 tool_calls 后自己决定要不要再发一次。
    """
    reply = transport.post(request)
    choice = reply["choices"][0]
    reason = choice["finish_reason"]
    message = choice["message"]

    added: list[dict] = [message]
    for call in message.get("tool_calls") or []:
        added.append(execute(call))
    request["messages"].extend(added)
    return reason, added


def main() -> None:
    transport = Transport()
    request = {
        "model": "demo-model-2024",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "订单 A1001 还能退吗？"},
        ],
        "tools": [ORDER_TOOL],
    }

    print("=== 请求（发出去的样子）===")
    print(json.dumps(request, ensure_ascii=False, indent=2))

    print()
    print("=== 第一次响应：没有答案，只有一个动作 ===")
    reason, added = one_round(request, transport)
    print(f"finish_reason = {reason}")
    print(json.dumps(transport.transcript[-1]["response"]["choices"][0]["message"],
                     ensure_ascii=False, indent=2))

    print()
    print("=== 执行并回灌后，messages 末尾的两条 ===")
    print(json.dumps(request["messages"][-2:], ensure_ascii=False, indent=2))

    print()
    print("=== 第二次响应：这一次才有答案 ===")
    reason, _ = one_round(request, transport)
    print(f"finish_reason = {reason}")
    print(f"content = {request['messages'][-1]['content']!r}")

    print()
    print("=== 两次 calls 的 token 账 ===")
    total = 0
    for i, t in enumerate(transport.transcript, 1):
        u = t["response"]["usage"]
        total += u["total_tokens"]
        print(f"  第 {i} 次：prompt={u['prompt_tokens']:<4} completion={u['completion_tokens']:<3} "
              f"total={u['total_tokens']}")
    print(f"  合计：{total} tokens，共 {transport.turns} 次请求")

    print()
    print("=== 关键对照：第二次请求比第一次多了什么 ===")
    first = transport.transcript[0]["request"]
    second = transport.transcript[1]["request"]
    print(f"  请求 1 的 messages 条数：{len(first['messages'])}")
    print(f"  请求 2 的 messages 条数：{len(second['messages'])}")
    print("  多出来的 role：", [m["role"] for m in second["messages"][len(first["messages"]):]])


if __name__ == "__main__":
    main()
