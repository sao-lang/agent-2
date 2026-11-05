"""第 6 章 B1：这个例子的五个工具 —— 声明、实现、注册表。

三段各管一件事：name 决定"调不调"，description 决定"该不该调"，
parameters 决定"填什么"。声明（给模型看）与实现（给调用方执行）是两份东西。

`TOOLS` 仍然是模块级列表，验证手册 A3「改 get_policy 的 description」改的就是它，
改完立刻生效（registry.declarations() 返回的就是这个列表对象本身）。
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from core.contracts import ToolSpec
from .data import CLAUSE_TEXT, ORDERS, POLICY
from .schemas import ClauseQuery, CouponQuery, FeeQuery, OrderQuery, PolicyQuery


# ── 第 6 章：工具的真实实现 ──────────────────────────────────────────────────
def get_order(order_id: str) -> dict:
    """查订单。不存在时抛 KeyError，由执行器转成 error 回灌——不是让程序崩掉。"""
    if order_id not in ORDERS:                       # 业务校验：模型可能编出不存在的订单号
        raise KeyError(f"订单不存在：{order_id}")      # 抛出的字符串最终会进 tool 消息
    return {"order_id": order_id, **ORDERS[order_id]}  # 返回值会被序列化成字符串回灌


def get_policy(category: str) -> dict:
    """查政策。category 已被 Literal 约束，这里可以直接下标。"""
    return {"category": category, **POLICY[category]}


def calc_shipping_fee(order_id: str, weight_kg: float) -> dict:
    """算运费：首重 1kg 8 元，续重每公斤 2 元。"""
    if order_id not in ORDERS:                                   # 同样的业务校验
        raise KeyError(f"订单不存在：{order_id}")
    fee = 8 + max(0.0, (weight_kg - 1)) * 2                      # max(0,...) 让 1kg 以内不出现负数续重
    return {"order_id": order_id, "weight_kg": weight_kg, "fee": round(fee, 2)}


def get_clause_text(category: str) -> dict:
    """取长文本。它存在的意义是"一定会撞上裁剪"，不是为了有用。"""
    return {"category": category, "text": CLAUSE_TEXT}


def check_coupon(order_id: str) -> dict:
    """恒定返回「无」。结果恒定 = 无论参数怎么变，结果指纹都一样。"""
    return {"coupon": "无", "note": "本平台目前不发券"}


# ── 第 6 章 B1：tools 声明（schema 由 pydantic 模型生成）─────────────────────
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "查订单状态、签收天数与商品类别。只查本账号订单，订单号形如 A1002。",
            "parameters": OrderQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy",
            "description": "查某一类商品的退货窗口与条款编号。窗口以本工具返回值为准。",
            "parameters": PolicyQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc_shipping_fee",
            "description": "算退回运费：首重 1kg 8 元，续重每公斤 2 元。",
            "parameters": FeeQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clause_text",
            # "很长，只在用户要求原文时调用"决定模型平时不会去调它，
            # 所以它天然是"上下文爆炸"的触发器（第 8 章）
            "description": "取条款全文。很长，只在用户要求原文时调用。",
            "parameters": ClauseQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_coupon",
            # "一律返回「无」"——恒定结果，天然是"换参数打转"的触发器（第 8 章）
            "description": "查订单有没有可用优惠券。本平台目前一律返回「无」。",
            "parameters": CouponQuery.model_json_schema(),
        },
    },
]


# 名字 -> (实现函数, 参数模型)。这张表是"工具名校验"的唯一依据：
# 模型给了表里没有的名字，就是一次必须被拦下的坏调用（第 6 章 B1 失败面）。
TOOL_IMPL: dict[str, tuple[Callable[..., dict], type[BaseModel]]] = {
    "get_order": (get_order, OrderQuery),
    "get_policy": (get_policy, PolicyQuery),
    "calc_shipping_fee": (calc_shipping_fee, FeeQuery),
    "get_clause_text": (get_clause_text, ClauseQuery),
    "check_coupon": (check_coupon, CouponQuery),
}


class DemoToolRegistry:
    """把"声明"和"实现"配成 ToolSpec，交给核心使用。

    实现 core.contracts.ToolRegistry 的两个方法即可；第 26 章换成本地 / MCP /
    Skill 时，只要另有对象实现这两个方法，run_loop() 一行都不用改。
    """

    def __init__(
        self,
        declarations: list[dict[str, Any]],
        impls: dict[str, tuple[Callable[..., dict], type[BaseModel]]],
    ) -> None:
        self._declarations = declarations
        self._specs: dict[str, ToolSpec] = {}
        for decl in declarations:
            fn = decl["function"]
            impl, arg_model = impls[fn["name"]]
            self._specs[fn["name"]] = ToolSpec(
                name=fn["name"],
                description=fn["description"],
                args_model=arg_model,
                impl=impl,
            )

    def declarations(self) -> list[dict[str, Any]]:
        # 返回同一个列表对象，所以改 TOOLS 里的 description 会立刻生效（A3 练习）
        return self._declarations

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)


REGISTRY = DemoToolRegistry(TOOLS, TOOL_IMPL)
