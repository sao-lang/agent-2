"""一个脚本化的"模型服务端"，供第 6 章使用。

不联网。响应体按 OpenAI 兼容格式手工构造，只固定形状，不代表真实模型输出。
服务端按"剧本"返回：剧本决定第几步给工具调用、第几步给答案。
"""

from __future__ import annotations

import copy
import json

ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_order",
        "description": '查询订单信息。返回 JSON：{"status": str, "signed_days_ago": int}。',
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
}

POLICY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_policy",
        "description": '查询退货政策。返回 JSON：{"window_days": int, "require_unopened": bool}。',
        "parameters": {"type": "object", "properties": {}},
    },
}

ORDERS = {"A1001": {"status": "已签收", "signed_days_ago": 3}}
POLICY = {"window_days": 7, "require_unopened": True}


def tool_call_reply(name: str, arguments: dict, step: int) -> dict:
    return {
        "id": f"chatcmpl-{step}",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{step}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 100 + step * 30,
            "completion_tokens": 18,
            "total_tokens": 118 + step * 30,
        },
    }


def answer_reply(text: str, step: int) -> dict:
    return {
        "id": f"chatcmpl-{step}",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100 + step * 30,
            "completion_tokens": 14,
            "total_tokens": 114 + step * 30,
        },
    }


class ScriptedModel:
    """按剧本应答。剧本是一个函数：(第几步, 请求) -> 响应。"""

    def __init__(self, script) -> None:
        self.script = script
        self.calls = 0

    def post(self, request: dict) -> dict:
        self.calls += 1
        return self.script(self.calls, copy.deepcopy(request))


def execute(call: dict) -> dict:
    """执行一条 tool_call，返回回灌用的 tool 消息。"""
    name = call["function"]["name"]
    try:
        args = json.loads(call["function"]["arguments"])
    except json.JSONDecodeError as e:
        result = {"error": f"参数不是合法 JSON：{e}"}
    else:
        if name == "get_order":
            result = ORDERS.get(args.get("order_id"), {"error": "订单不存在"})
        elif name == "get_policy":
            result = POLICY
        else:
            result = {"error": f"未知工具：{name}"}
    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "content": json.dumps(result, ensure_ascii=False),
    }


def new_request() -> dict:
    return {
        "model": "demo-model-2024",
        "messages": [
            {"role": "system", "content": "你是退货客服。"},
            {"role": "user", "content": "订单 A1001 还能退吗？"},
        ],
        "tools": [ORDER_TOOL, POLICY_TOOL],
    }
