"""工具清单与实现的一致性检查。

只做静态核对，不需要模型，也不需要网络。它拦的是三类"以模型答错为表现形式"的
契约破损：声明了没实现、实现了没声明、必填参数没有类型声明。
"""

from __future__ import annotations

from transport import ORDER_TOOL


def send_sms(order_id: str) -> dict:
    """有副作用的工具：实现存在，但没有出现在 tools 里。"""
    return {"sent": True, "order_id": order_id}


IMPL = {"get_order": object, "send_sms": send_sms}


def audit_tools(tools: list[dict], impl: dict[str, object]) -> list[str]:
    """检查工具清单与实现是否一致。返回问题列表，空表示一致。"""
    problems: list[str] = []
    declared = {t["function"]["name"] for t in tools}

    for name in sorted(declared - set(impl)):
        problems.append(f"声明了但没有实现：{name}")
    for name in sorted(set(impl) - declared):
        problems.append(f"实现了但没有声明：{name}")

    for tool in tools:
        fn = tool["function"]
        name = fn["name"]
        if name in impl and not fn.get("description"):
            problems.append(f"缺 description：{name}")
        params = fn.get("parameters", {})
        props = params.get("properties", {})
        for field in params.get("required", []):
            if field not in props:
                problems.append(f"{name} 的必填参数 {field} 没有类型声明")
    return problems


def main() -> None:
    print("一致的清单：", audit_tools([ORDER_TOOL], {"get_order": object}) or "无问题")
    print("多出一个实现：", audit_tools([ORDER_TOOL], IMPL))

    no_desc = {
        "type": "function",
        "function": {
            "name": "get_order",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": ["order_id"],
            },
        },
    }
    print("缺说明与参数声明：", audit_tools([no_desc], {"get_order": object}))


if __name__ == "__main__":
    main()
