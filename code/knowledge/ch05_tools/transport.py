"""一个脚本化的"模型服务端"，用来演示工具调用的往返。

不联网。本模块把请求和响应都做成**真实的 JSON 文本**，每一次往返都写进 transcript。
响应体按 OpenAI 兼容格式手工构造，用来固定 JSON 的形状、方便逐字段核对；
它不是真实模型的输出，正文里对应的地方都标了这一点。
"""

from __future__ import annotations

import copy
import json

# 第 4 章那份结构化输出请求，原封不动地放在这里做对照：内容一模一样，
# 只是用 speech_to_json 把 JSON 读出来，不涉及 tools 字段。
STRUCTURED_OUTPUT_REQUEST = {
    "model": "demo-model-2024",
    "messages": [
        {"role": "system", "content": "你是电商客服，只处理退货相关问题。"},
        {"role": "user", "content": "订单 A1001：签收于 3 天前，商品未拆封。是否可退？"},
    ],
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "refund_check",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "days": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "days", "reason"],
                "additionalProperties": False,
            },
        },
    },
}

STRUCTURED_OUTPUT_RESPONSE = {
    "id": "chatcmpl-10",
    "object": "chat.completion",
    "model": "demo-model-2024",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": '{"order_id": "A1001", "days": 3, "reason": "未拆封且在 7 天内"}',
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 96, "completion_tokens": 31, "total_tokens": 127},
}

# 工具定义：一个只描述"能做哪件事"，一个把"结果长什么样"也写进了说明。
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市当前的天气状况。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，例如 杭州"},
            },
            "required": ["city"],
        },
    },
}

ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_order",
        "description": (
            "查询订单信息。返回 JSON，字段为 "
            '{"status": "已签收", "signed_days_ago": 3}。'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，例如 A1001"},
            },
            "required": ["order_id"],
        },
    },
}

SYSTEM = "你是一个只处理退货问题的客服助手。"


def speech_to_json(text: str) -> str:
    """这段文字说的是什么形状：是一个合法的 JSON 对象，还是不是。

    人能看到说明文字，模型看不到：它拿到的是这段文字的 token。
    这个函数回答的是"模型收到的东西够不够它知道有个工具能查天气"。
    """
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return "不是 JSON"
    if isinstance(obj, dict):
        keys = "、".join(obj.keys())
        return f"是一个 JSON 对象，顶层键：{keys}"
    return f"是 JSON，但顶层是 {type(obj).__name__}"


def _first_user_text(messages: list[dict]) -> str:
    for m in messages:
        if m["role"] == "user":
            return m["content"]
    return ""


def _has_tool_result(messages: list[dict]) -> bool:
    return any(m["role"] == "tool" for m in messages)


def _tool_names(request: dict) -> set[str]:
    return {t.get("function", {}).get("name", "") for t in request.get("tools", [])}


def respond(request: dict) -> dict:
    """按请求里的标记返回响应。脚本化：只看 messages 与 tools，不调用任何模型。"""
    messages = request["messages"]
    text = _first_user_text(messages)
    names = _tool_names(request)
    has_order = "get_order" in names
    has_weather = "get_weather" in names

    # 标记一：tools 里没有 get_weather，模型不会把它当成一个可选动作。
    # 它只有文字可依赖，只能编一个看起来合理的天气。
    if "天气" in text and not has_weather:
        if "杭州" in text:
            return _reply("杭州今天多云转晴，最高气温 24°C。", "stop", 41, 12)
        return _reply("我无法查询天气。", "stop", 38, 8)

    # 标记二：有 get_weather，模型输出的是一个动作，不是答案。
    if "天气" in text and has_weather:
        city = "杭州" if "杭州" in text else "北京"
        args = json.dumps({"city": city}, ensure_ascii=False)
        return _tool_reply("call_weather_01", "get_weather", args, 88, 15)

    # 标记三：退货问题，工具表里有查订单，但对话里还没有订单数据。
    if has_order and not _has_tool_result(messages):
        return _tool_reply("call_order_01", "get_order", '{"order_id": "A1001"}', 104, 17)

    # 标记四：已经有工具结果回灌，这一步才可能给出结论。
    if has_order and _has_tool_result(messages):
        state = json.loads([m for m in messages if m["role"] == "tool"][-1]["content"])
        days = state.get("signed_days_ago")
        if isinstance(days, int) and days <= 7:
            return _reply(f"可以退：已签收 {days} 天，在 7 天内。", "stop", 138, 12)
        return _reply(f"不可以退：已签收 {days} 天，超过 7 天。", "stop", 138, 13)

    return _reply("我只能回答退货相关的问题。", "stop", 30, 9)


def _usage(prompt: int, completion: int) -> dict:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _reply(content: str, reason: str, prompt: int, completion: int) -> dict:
    return {
        "id": f"chatcmpl-{prompt}{completion}",
        "object": "chat.completion",
        "model": "demo-model-2024",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": reason,
            }
        ],
        "usage": _usage(prompt, completion),
    }


def _tool_reply(
    call_id: str, name: str, arguments: str, prompt: int, completion: int
) -> dict:
    return {
        "id": f"chatcmpl-{prompt}{completion}",
        "object": "chat.completion",
        "model": "demo-model-2024",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": _usage(prompt, completion),
    }


class Transport:
    """记录每一次请求与响应的原文，用来展示"模型看到的是什么"。"""

    def __init__(self) -> None:
        self.transcript: list[dict] = []

    def post(self, request: dict) -> dict:
        response = respond(copy.deepcopy(request))
        self.transcript.append(
            {
                "request": copy.deepcopy(request),
                "request_text": json.dumps(request, ensure_ascii=False),
                "response": copy.deepcopy(response),
                "response_text": json.dumps(response, ensure_ascii=False, indent=2),
            }
        )
        return copy.deepcopy(response)

    @property
    def turns(self) -> int:
        return len(self.transcript)

    def dump(self) -> str:
        """把整段往返拼成一份文本，用来估算"模型这次看到了多少字"。"""
        return "\n".join(t["request_text"] for t in self.transcript)
