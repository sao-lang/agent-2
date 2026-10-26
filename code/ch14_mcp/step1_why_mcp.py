"""第 14 章 step1：MCP 到底解决了什么——手写一个最小协议（离线）。

运行：
    python code/ch14_mcp/step1_why_mcp.py

上一级的痛点（第 13 章）：工具调用会了，但每个应用都要重写一遍接入：
                     Cursor 写一套 GitHub 连接，你的 Agent 又写一套。

这一级做什么：先看清"没有 MCP 时的重复"，再手写一个最小协议（JSON-RPC 风格），
             让同一台"服务"被两个不同的"宿主"用同一份代码接入。

  · 三段式的 ① 声明，从"进程内函数注册"变成"跨进程协议发现"
  · 三段式的 ③ 执行，从"直接调函数"变成"发 RPC 请求"
  · **② 决策完全不变** —— 模型看到的还是 name + description + schema

关键认知：MCP 没有改变"工具调用"这件事，它改变的是**工具从哪来**。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


# ============================================================ MCP Server（服务端）
@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]


class McpServer:
    """一个最小的 MCP 风格服务端。

    真实 MCP 用 JSON-RPC 2.0 over stdio/HTTP，方法名是：
      initialize / tools/list / tools/call
    这里保留这三个方法，让你看清协议长什么样。
    """

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self.name = name
        self.version = version
        self.tools: dict[str, McpTool] = {}
        self.initialized = False

    def add_tool(self, t: McpTool) -> None:
        self.tools[t.name] = t

    # ---- 协议方法 ----
    def handle(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if method == "initialize":
            self.initialized = True
            return {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": self.name, "version": self.version},
                "capabilities": {"tools": {"listChanged": False}},
            }
        if not self.initialized:
            return {"error": {"code": -32002, "message": "未初始化，先调 initialize"}}

        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.input_schema,
                    }
                    for t in self.tools.values()
                ]
            }

        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})
            t = self.tools.get(name)
            if t is None:
                return {"error": {"code": -32602, "message": f"工具不存在：{name}"}}
            try:
                out = t.handler(**args)
                return {"content": [{"type": "text", "text": str(out)}], "isError": False}
            except Exception as e:  # noqa: BLE001 —— 服务端必须吃下一切异常
                return {
                    "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                    "isError": True,
                }

        return {"error": {"code": -32601, "message": f"未知方法：{method}"}}


# ============================================================ MCP Client（客户端）
class McpClient:
    """Host 内部的一条连接。真实实现会走 stdio 子进程或 HTTP。

    它把 `server.handle()` 换成"发消息"，但**接口完全一样**。
    """

    def __init__(self, server: McpServer) -> None:
        self.server = server
        self.tools: list[dict[str, Any]] = []

    def initialize(self) -> dict[str, Any]:
        info = self.server.handle("initialize")
        self.tools = self.server.handle("tools/list")["tools"]
        return info

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.server.handle("tools/call", {"name": name, "arguments": arguments})


# ============================================================ 两个不同的"宿主"
class HostA:
    """宿主 A：一个 Agent。它把 MCP 工具转成自己的工具格式。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.clients: list[McpClient] = []

    def connect(self, server: McpServer) -> None:
        c = McpClient(server)
        c.initialize()
        self.clients.append(c)

    def tool_manifest(self) -> str:
        """把发现到的工具渲染成"给模型看的清单"（三段式的 ①）。"""
        lines = []
        for c in self.clients:
            for t in c.tools:
                props = ", ".join(t["inputSchema"].get("properties", {}))
                lines.append(f"- {t['name']}({props})：{t['description']}")
        return "\n".join(lines)

    def invoke(self, name: str, args: dict[str, Any]) -> str:
        for c in self.clients:
            if any(t["name"] == name for t in c.tools):
                r = c.call(name, args)
                return r["content"][0]["text"]
        return f"未知工具 {name}"


class HostB:
    """宿主 B：另一个完全不同的应用，用**同一份服务**接入，代码零改动。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.client: McpClient | None = None

    def connect(self, server: McpServer) -> None:
        self.client = McpClient(server)
        self.client.initialize()

    def invoke(self, name: str, args: dict[str, Any]) -> str:
        assert self.client is not None
        return self.client.call(name, args)["content"][0]["text"]


# ============================================================ 建服务
def build_weather_server() -> McpServer:
    s = McpServer("weather-mcp", "1.0.0")
    s.add_tool(
        McpTool(
            name="get_weather",
            description="查询城市当前天气。当用户问天气、气温、下雨时用这个。",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名，如 杭州"}},
                "required": ["city"],
            },
            handler=lambda city: f"{city} 晴 25°C",
        )
    )
    return s


def build_order_server() -> McpServer:
    s = McpServer("order-mcp", "2.1.0")
    s.add_tool(
        McpTool(
            name="query_order_status",
            description="按订单号查询订单状态。当用户提到订单、物流、签收时用这个。",
            input_schema={
                "type": "object",
                "properties": {"order_id": {"type": "string", "pattern": "^[A-Z]\\d{3,6}$"}},
                "required": ["order_id"],
            },
            handler=lambda order_id: {"A12345": "已签收3天"}.get(order_id, "订单不存在"),
        )
    )
    return s


def main() -> None:
    print("=" * 90)
    print("① 没有 MCP：每个宿主都要自己接一遍")
    print("=" * 90)
    print("  宿主 A（Agent）→ 自己写 weather 连接器")
    print("  宿主 B（IDE）  → 又写一遍 weather 连接器")
    print("  宿主 C（客服） → 再写一遍 ……")
    print("  → N 个应用 × M 个外部系统 = **N×M 份适配代码**")

    print("\n" + "=" * 90)
    print("② 有 MCP：N + M")
    print("=" * 90)
    print("  服务端写一次（暴露协议），N 个宿主都只需实现**一个**客户端")

    weather = build_weather_server()
    order = build_order_server()

    a = HostA("售后 Agent")
    a.connect(weather)
    a.connect(order)

    b = HostB("IDE 助手")
    b.connect(weather)

    print("\n" + "=" * 90)
    print("③ 宿主 A 从 MCP 发现到的工具清单（这就是模型看到的）")
    print("=" * 90)
    print(a.tool_manifest())

    print("\n" + "=" * 90)
    print("④ 同一个服务，两个宿主分别调用（代码零改动）")
    print("=" * 90)
    print(f"  宿主 A（{a.name}）  get_weather(杭州) → {a.invoke('get_weather', {'city': '杭州'})}")
    print(f"  宿主 A（{a.name}）  query_order_status(A12345) → {a.invoke('query_order_status', {'order_id': 'A12345'})}")
    print(f"  宿主 B（{b.name}）  get_weather(北京) → {b.invoke('get_weather', {'city': '北京'})}")

    print("\n" + "=" * 90)
    print("⑤ 协议长什么样：一次 tools/call 的原始报文")
    print("=" * 90)
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "get_weather", "arguments": {"city": "杭州"}}}
    print("  请求：")
    print("    " + json.dumps(req, ensure_ascii=False))
    resp = weather.handle("tools/call", {"name": "get_weather", "arguments": {"city": "杭州"}})
    print("  响应：")
    print("    " + json.dumps({"jsonrpc": "2.0", "id": 1, "result": resp}, ensure_ascii=False))

    print("\n" + "=" * 90)
    print("⑥ MCP 没改变什么")
    print("=" * 90)
    print("  · 三段式的 ② 决策**完全不变**：模型看到的还是 name + description + schema")
    print("  · 只是 ① 声明变成了'协议发现'，③ 执行变成了'发 RPC'")
    print("  · 所以第 13 章的四层安全检查**一样要做**，而且要在服务端再做一遍")
    print("    （客户端拦一次，服务端再拦一次 —— 服务端不知道调用方是谁）")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · MCP 解决的是**接入方式**，不是**能力本身**。")
    print("  · 价值：`N×M 份适配` → `N+M 份`。工具写一次，到处能用。")
    print("  · 协议只有三个核心方法：`initialize` / `tools/list` / `tools/call`。")
    print("  · **但它也带来了新风险**：服务端可能是别人写的，你必须自己做白名单 + 校验。")
    print()
    print("  下一级（step2）：MCP 的三种能力（tools/resources/prompts）怎么区分。")

    assert a.invoke("get_weather", {"city": "杭州"}).startswith("杭州")
    assert "订单不存在" in a.invoke("query_order_status", {"order_id": "B777"})


if __name__ == "__main__":
    main()
