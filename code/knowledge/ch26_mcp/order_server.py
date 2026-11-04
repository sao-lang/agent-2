"""一个退货域的 MCP server：三个工具、一份资源、一个提示词模板。

运行（stdio，供 MCP Host 拉起）：
    python code/knowledge/ch26_mcp/order_server.py

运行（HTTP，供远端 Host 连）：
    python code/knowledge/ch26_mcp/order_server.py --http

工具与资源都不联网：订单与政策是本地常数，方便对照输出。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

mcp = FastMCP(
    name="order-policy",
    instructions=(
        "退货域的能力面。查订单用 get_order，查政策窗口用 get_policy，"
        "判定前必须同时拿到两者的数字；结论只能来自这四个数字，不靠推测。"
    ),
)

ORDERS: dict[str, dict] = {
    "A1001": {"order_id": "A1001", "status": "已签收", "signed_days_ago": 3, "category": "普通"},
    "A1002": {"order_id": "A1002", "status": "已签收", "signed_days_ago": 9, "category": "普通"},
    "B2001": {"order_id": "B2001", "status": "已签收", "signed_days_ago": 2, "category": "生鲜"},
    "C3001": {"order_id": "C3001", "status": "未发货", "signed_days_ago": None, "category": "定制"},
}

POLICY = {
    "普通": {"window_days": 7, "clause": "P-7", "condition": "商品未拆封或不影响二次销售"},
    "生鲜": {"window_days": 1, "clause": "P-9", "condition": "签收 24 小时内且变质"},
    "定制": {"window_days": 0, "clause": "P-12", "condition": "定制商品不支持无理由退货"},
}


@dataclass
class Order:
    order_id: str
    status: str
    signed_days_ago: int | None
    category: str


@mcp.tool(
    annotations={"readOnlyHint": True, "title": "查询订单"},
    tags={"read", "order"},
)
def get_order(
    order_id: Annotated[str, Field(pattern=r"^[A-Z]\d{4}$", description="订单号，例如 A1001")],
) -> Order:
    """按订单号取状态、签收天数与商品类别。只查本账号订单。"""
    if order_id not in ORDERS:
        raise ToolError(f"订单不存在：{order_id}（本 server 只有 A1001/A1002/B2001/C3001）")
    return Order(**ORDERS[order_id])


@mcp.tool(annotations={"readOnlyHint": True, "title": "查询退货政策"})
def get_policy(
    category: Literal["普通", "生鲜", "定制"] = "普通",
) -> dict:
    """取某一类商品的退货窗口与条款编号。窗口以这里返回的为准，不要在提示词里写死。"""
    return {"category": category, **POLICY[category]}


@mcp.tool(title="给出退货判定")
def review_refund(
    order_id: Annotated[str, Field(description="订单号")],
    unopened: Annotated[bool, Field(description="商品是否未拆封")] = True,
) -> dict:
    """把两个查询合成一条判定。判定只看数字与规则，不做任何推测。"""
    data = ORDERS.get(order_id)
    if data is None:
        raise ToolError(f"订单不存在：{order_id}")
    order = Order(**data)
    if order.signed_days_ago is None:
        return {"order_id": order_id, "conclusion": "待定", "reason": "订单尚未签收，无签收天数"}

    policy = POLICY[order.category]
    within = order.signed_days_ago <= policy["window_days"]
    eligible = within and (unopened or order.category == "生鲜")
    return {
        "order_id": order_id,
        "category": order.category,
        "signed_days_ago": order.signed_days_ago,
        "window_days": policy["window_days"],
        "clause": policy["clause"],
        "eligible": eligible,
        "conclusion": "可退" if eligible else "不可退",
        "reason": policy["condition"] if eligible else "超出窗口或商品状态不符",
    }


@mcp.tool(annotations={"readOnlyHint": True, "title": "列出订单"})
def list_orders(
    limit: Annotated[int, Field(ge=1, le=20, description="最多返回几条")] = 5,
) -> list[dict]:
    """按签收天数升序列出最近的订单，用于"我有哪些单要处理"这类问题。"""
    rows = sorted(ORDERS.values(), key=lambda r: r["signed_days_ago"] or 999)
    return rows[:limit]


@mcp.tool(annotations={"readOnlyHint": True, "title": "查询物流"})
def get_logistics(order_id: str) -> dict:
    """取物流单号与最近一条轨迹。与退货判定无关，按需单独调用。"""
    if order_id not in ORDERS:
        raise ToolError(f"订单不存在：{order_id}")
    return {"order_id": order_id, "carrier": "顺丰", "tracking": "SF1234567890", "last": "已签收"}


@mcp.tool(
    annotations={"readOnlyHint": False, "destructiveHint": False, "title": "创建退货单"},
    tags={"write"},
)
def create_return(
    order_id: Annotated[str, Field(description="订单号")],
    reason: Annotated[str, Field(min_length=4, max_length=40, description="退货原因，至少 4 字")],
) -> dict:
    """创建退货单。写操作，真实环境里要再过一道人工审批。"""
    if order_id not in ORDERS:
        raise ToolError(f"订单不存在：{order_id}")
    return {"return_id": f"R-{order_id}", "order_id": order_id, "status": "已受理", "reason": reason}


@mcp.resource("policy://refund/{category}", mime_type="text/markdown")
def refund_clause(category: str) -> str:
    """某一类商品的退货条款原文。按需读取，不进工具清单。"""
    row = POLICY.get(category)
    if row is None:
        raise ValueError(f"未知类别：{category}")
    return (
        f"# {category}商品退货条款（{row['clause']}）\n\n"
        f"- 窗口：签收后 {row['window_days']} 天内\n"
        f"- 条件：{row['condition']}\n"
    )


@mcp.prompt(title="退货审查流程")
def review_flow(order_id: str) -> str:
    """把一次退货审查的步骤固化成提示词，Host 可以直接取用。"""
    return (
        f"审查订单 {order_id} 能否退货。\n"
        "1. 调 get_order 取 signed_days_ago 与 category；\n"
        "2. 调 get_policy 取 window_days 与 clause；\n"
        "3. 只依据这两个数字判定，相等算可退；\n"
        "4. 回复必须带条款编号，数字缺失时说缺什么。"
    )


if __name__ == "__main__":
    transport = "http" if "--http" in sys.argv else "stdio"
    if transport == "http":
        mcp.run(transport="http", host="127.0.0.1", port=8765)
    else:
        mcp.run(transport="stdio")
