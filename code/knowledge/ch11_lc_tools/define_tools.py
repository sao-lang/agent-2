"""同一个工具的三份定义：装饰器、BaseTool 子类、StructuredTool.from_function。

三份代码产出的是同一个东西——`name`、`description`、`args`、`args_schema`，
再被编码成请求里那段 `parameters`。差别在参数说明写在哪、校验由谁做。

不联网，也不需要模型：这一节只做定义，不发请求。
"""

from __future__ import annotations

import json
from typing import Any, Type

from langchain_core.tools import BaseTool, StructuredTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

DESCRIPTION = '查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。只查本账号订单。'


class OrderQuery(BaseModel):
    """get_order 的参数。字段说明原样进 schema，也原样进请求。"""

    order_id: str = Field(description="订单号，例如 A1001")
    detail: bool = Field(default=False, description="是否返回明细")


def fetch(order_id: str, detail: bool = False) -> str:
    """真正查一次。三份定义最终都走这一个函数。"""
    return json.dumps({"status": "已签收", "signed_days_ago": 3, "detail": detail},
                      ensure_ascii=False)


@tool("get_order", args_schema=OrderQuery)
def get_order(order_id: str, detail: bool = False) -> str:
    """查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。只查本账号订单。"""
    return fetch(order_id, detail)


class GetOrderTool(BaseTool):
    """子类写法：名字、说明、参数模型都是类属性，执行逻辑在 `_run`。"""

    name: str = "get_order"
    description: str = DESCRIPTION
    args_schema: Type[BaseModel] = OrderQuery

    def _run(self, order_id: str, detail: bool = False) -> str:
        return fetch(order_id, detail)


structured = StructuredTool.from_function(
    func=fetch,
    name="get_order",
    description=DESCRIPTION,
    args_schema=OrderQuery,
)


def describe(label: str, t: Any) -> None:
    """一个工具对象对外暴露的四个属性，以及它最终进请求的那段 parameters。"""
    encoded = convert_to_openai_tool(t)["function"]
    print(f"  {label}")
    print(f"    name        = {t.name}")
    print(f"    description = {t.description}")
    print(f"    args        = {json.dumps(t.args, ensure_ascii=False)}")
    print(f"    args_schema = {t.args_schema.__name__}")
    print(f"    进请求的 parameters = {json.dumps(encoded['parameters'], ensure_ascii=False)}")


def main() -> None:
    print("=== 一、三个属性与一份 parameters ===")
    describe("装饰器 @tool(args_schema=OrderQuery)", get_order)
    describe("BaseTool 子类", GetOrderTool())
    describe("StructuredTool.from_function(args_schema=OrderQuery)", structured)

    print()
    print("=== 二、三份定义编码出来的 tools 项逐字相同 ===")
    encoded = [json.dumps(convert_to_openai_tool(t)["function"], sort_keys=True)
               for t in (get_order, GetOrderTool(), structured)]
    print(f"  互不相同的份数 = {len(set(encoded))}（1 表示三份完全相同）")
    print(f"  每份的长度     = {len(encoded[0])} 字符")
    print(f"  调用结果       = {get_order.invoke({'order_id': 'A1001'})}")

    print()
    print("=== 三、参数校验发生在本地，不花一次调用 ===")
    for label, payload in [("缺必填", {}),
                           ("类型错", {"order_id": 1001}),
                           ("多余键", {"order_id": "A1001", "wind": 3})]:
        try:
            print(f"  {label} -> {get_order.invoke(payload)}")
        except Exception as exc:
            first_line = str(exc).splitlines()[2].strip()
            print(f"  {label} -> {type(exc).__name__}：{first_line}")

    print()
    print("=== 四、两处不在定义时出现的报错 ===")
    definition_errors()


def definition_errors() -> None:
    """没 docstring 的定义阶段就拒；args_schema 与签名不符的拖到调用时才炸。"""

    def no_doc(order_id: str) -> str:
        return order_id

    try:
        tool("no_doc")(no_doc)
    except Exception as exc:
        print(f"  没有 docstring 也没有 description -> {type(exc).__name__}: {exc}")

    class WrongQuery(BaseModel):
        city: str = Field(description="城市名")

    mismatched = StructuredTool.from_function(func=fetch, name="mismatch",
                                             description="参数模型与签名不符。",
                                             args_schema=WrongQuery)
    try:
        mismatched.invoke({"city": "杭州"})
    except Exception as exc:
        print(f"  args_schema 与签名不符 -> {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
