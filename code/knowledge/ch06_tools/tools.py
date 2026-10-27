"""本章共用：工具定义、工具实现、一份假数据。

工具定义是手写的 JSON Schema（生产里通常从函数签名或 pydantic 模型生成，
见 `schema_from_signature.py`）。工具实现是普通 Python 函数，模型碰不到它。
"""

from __future__ import annotations

import json

ORDERS = {
    "A1001": {"status": "已签收", "signed_days_ago": 3},
    "A1002": {"status": "已签收", "signed_days_ago": 40},
}

WEATHER = {"杭州": {"sky": "多云转晴", "celsius": 24}}


def get_order(order_id: str) -> dict:
    """查询订单。真实系统里这在数据库里，这里用字面量代替。"""
    if order_id not in ORDERS:
        raise KeyError(f"订单不存在：{order_id}")
    return ORDERS[order_id]


def get_weather(city: str) -> dict:
    """查询城市天气。只认 WEATHER 里有的城市。"""
    if city not in WEATHER:
        raise KeyError(f"没有这个城市：{city}")
    return WEATHER[city]


# 名字 → 函数。工具调用只能调到这里有的东西。
TOOL_IMPL = {"get_order": get_order, "get_weather": get_weather}

SYSTEM = "你是一个只处理退货问题的客服助手。"

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

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市当前的天气。返回 JSON，字段为 sky、celsius。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，例如 杭州"},
            },
            "required": ["city"],
        },
    },
}


def tool_call(name: str, args: dict, call_id: str = "call_demo") -> dict:
    """构造响应里的一个 `tool_calls` 元素。

    注意 `arguments` 是 json.dumps 之后的**字符串**，与厂商响应一致。
    """
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }
