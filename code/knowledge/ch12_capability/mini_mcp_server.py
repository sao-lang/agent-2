"""最小 MCP server：stdin 读一行 JSON-RPC，stdout 写一行响应。

不是完整实现：只有 initialize / tools/list / tools/call 三个方法，
未声明的方法一律返回错误（默认拒绝）。
"""

from __future__ import annotations

import json
import sys

ORDERS = {"A1001": {"status": "已签收", "signed_days_ago": 3}}

TOOLS = [
    {
        "name": "get_order",
        "description": "查询订单。返回 JSON：status / signed_days_ago。",
        "inputSchema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_policy",
        "description": "查询退货政策。返回 JSON：window_days。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle(req: dict) -> dict:
    mid = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "mini-order", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "get_order":
            data = ORDERS.get(args.get("order_id"), {"error": "订单不存在"})
        elif name == "get_policy":
            data = {"window_days": 7}
        else:
            return error(mid, -32601, f"未声明的工具：{name}")
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]},
        }

    return error(mid, -32601, f"未声明的方法：{method}")


def error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps(error(None, -32700, f"解析失败：{e}")), flush=True)
            continue
        print(json.dumps(handle(req), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
