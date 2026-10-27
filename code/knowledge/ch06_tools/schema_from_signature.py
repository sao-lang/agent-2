"""工具 schema 从哪来：手写、函数签名、pydantic 模型。

三条路产出的是同一样东西——一段 JSON Schema，塞进请求的 `tools` 字段。
差别在维护成本和漏写风险：签名版不会漏参数，pydantic 版连类型校验一起拿到。
"""

from __future__ import annotations

import inspect
import json
from typing import get_type_hints

from pydantic import BaseModel, Field

from tools import ORDER_TOOL, get_order

TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def schema_from_function(fn) -> dict:
    """从函数签名生成工具定义。

    annotation 决定参数类型，有没有默认值决定它是否必填。
    参数说明只能来自 docstring，所以这里它是空的。
    """
    hints = get_type_hints(fn)          # 文件顶上有 from __future__ import annotations，
    props: dict = {}                    # 注解默认是字符串，要先解析回类型
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = {"type": TYPES[hints[name]]}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip(),
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


class GetOrderArgs(BaseModel):
    """get_order 的参数。字段的 description 会原样进 schema。"""

    order_id: str = Field(description="订单号，例如 A1001")


def schema_from_model(model: type[BaseModel]) -> dict:
    """从 pydantic 模型生成工具定义。类型校验和 schema 用的是同一份声明。"""
    return {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": (
                "查询订单信息。返回 JSON，字段为 "
                '{"status": "已签收", "signed_days_ago": 3}。'
            ),
            "parameters": model.model_json_schema(),
        },
    }


def describe(label: str, tool: dict) -> None:
    """打印一份 schema 的形状统计：它到底带了哪些东西。"""
    params = tool["function"]["parameters"]
    text = json.dumps(params, ensure_ascii=False)
    prop = params["properties"]["order_id"]
    print(f"  {label}：keys={sorted(params)}")
    print(f"    参数说明={'有' if 'description' in prop else '没有'}  "
          f"title={'有' if 'title' in prop else '没有'}  "
          f"parameters 序列化后 {len(text)} 字符")


def main() -> None:
    handwritten = ORDER_TOOL
    by_signature = schema_from_function(get_order)
    by_model = schema_from_model(GetOrderArgs)

    print("=== 一、手写的那份（tools.py 里的 ORDER_TOOL）===")
    print(json.dumps(handwritten, ensure_ascii=False, indent=2))

    print()
    print("=== 二、从函数签名生成 ===")
    print(json.dumps(by_signature, ensure_ascii=False, indent=2))

    print()
    print("=== 三、从 pydantic 模型生成 ===")
    print(json.dumps(by_model, ensure_ascii=False, indent=2))

    print()
    print("=== 三份 parameters 的差别 ===")
    describe("手写版", handwritten)
    describe("签名版", by_signature)
    describe("pydantic 版", by_model)

    print()
    print("=== pydantic 版多出来的那段文字 ===")
    print(json.dumps(GetOrderArgs.model_json_schema(), ensure_ascii=False))


if __name__ == "__main__":
    main()
