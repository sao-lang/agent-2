"""最小 MCP 演示：Host / Client / Server 三个角色、工具前缀、默认拒绝。

只用标准库。这不是 MCP 的实现，而是一次最小 JSON-RPC 往返：
server 是一个独立子进程，一行一条消息，stdin 收、stdout 发。
真实项目用 mcp 包（pip install mcp），方法名与消息形状一致。

运行：python code/knowledge/ch26_skills/mcp_min_demo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

SERVER_INFO = {"name": "mini-order", "version": "0.1.0"}

# ---------------------------------------------------------------- server 侧

# server 只声明这三个工具，未声明的一律拒绝。
TOOLS = {
    "get_order": {
        "description": "查询订单。返回 JSON：status / signed_days_ago。",
        "handler": lambda args: {"status": "已签收", "signed_days_ago": 3},
    },
    "get_policy": {
        "description": "查询退货政策。返回 JSON：window_days。",
        "handler": lambda args: {"window_days": 7},
    },
    "refund_apply": {
        "description": "提交退款申请。写操作，需要审批。",
        "handler": lambda args: {"refund_id": "R9001"},
    },
}


def dispatch(req: dict) -> dict:
    """一条请求进来，一条响应出去。"""
    mid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {}},
        }
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": t["description"]}
                            for n, t in TOOLS.items()]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": f"未声明的工具：{name}"}}
        data = TOOLS[name]["handler"](params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"未声明的方法：{method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve() -> None:
    """stdio 传输：读一行、写一行。日志不能写 stdout。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        print(json.dumps(dispatch(json.loads(line)), ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- Host 侧

class Client:
    """Host 里的一个连接器：与一个 server 一对一。"""

    def __init__(self, command: list[str]) -> None:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
        )

    def request(self, method: str, params: dict | None = None, mid: int = 1) -> dict:
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        return json.loads(line) if line.strip() else {"error": {"message": "server 无输出"}}

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=5)


def namespaced(server: str, tool: str) -> str:
    """外部工具进模型可见清单时加前缀，避免与本地工具撞名。"""
    return f"{server}__{tool}"


def as_tool_message(call_id: str, resp: dict) -> dict:
    """MCP 的 content 数组 -> 第 6 章那条 tool 消息。"""
    if "error" in resp:
        payload = json.dumps({"error": resp["error"]["message"]}, ensure_ascii=False)
    else:
        blocks = resp["result"].get("content", [])
        payload = "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or "{}"
    return {"role": "tool", "tool_call_id": call_id, "content": payload}


def host_call(client: Client, allow: list[str], name: str,
              args: dict, mid: int) -> dict:
    """Host 是唯一决策点：不在本阶段白名单里的调用，不发给 server。"""
    if name not in allow:
        return {"error": {"code": -32000,
                          "message": f"工具不在本阶段的可见集：{name}"}}
    return client.request("tools/call", {"name": name, "arguments": args}, mid)


def main() -> None:
    server_cmd = [sys.executable, os.path.abspath(__file__), "--serve"]
    allow = ["get_order", "get_policy"]          # Host 侧白名单：三个声明里只接两个
    client = Client(server_cmd)

    print("=== 1. initialize（Host 起一个 Client，连一个 stdio server）===")
    print(json.dumps(client.request("initialize", mid=1), ensure_ascii=False, indent=2))

    print()
    print("=== 2. tools/list：Host 先按白名单过滤，再加前缀进清单 ===")
    declared = client.request("tools/list", mid=2)["result"]["tools"]
    for t in declared:
        if t["name"] not in allow:
            print(f"  （{t['name']} 已声明，但不在 Host 白名单里，不进清单）")
            continue
        print(f"  {namespaced('order', t['name']):<20} <- {t['description']}")

    print()
    print("=== 3. tools/call -> tool 消息 ===")
    resp = host_call(client, allow, "get_order", {"order_id": "A1001"}, 3)
    print(" ", json.dumps(resp, ensure_ascii=False))
    print(" ", as_tool_message("call_3", resp))

    print()
    print("=== 4. 未声明的工具（server 侧默认拒绝）===")
    print(" ", json.dumps(host_call(client, ["drop_table"], "drop_table", {}, 4),
                            ensure_ascii=False))

    print()
    print("=== 5. Host 侧默认拒绝（声明过，但本阶段不给）===")
    print(" ", json.dumps(host_call(client, allow, "refund_apply", {"order_id": "A1001"}, 5),
                            ensure_ascii=False))

    client.close()


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        main()
