"""MCP client：连上 order_server，按需加载工具、资源与提示词。

两种连法：
    同进程（示例默认）：Client(server 对象)，走内存传输，不需要子进程
    子进程（生产常用）：Client("code/knowledge/ch26_mcp/order_server.py")，走 stdio
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastmcp import Client

# 服务端把工具错误写成日志，示例里只关心返回值，先把日志压掉
logging.disable(logging.CRITICAL)

from order_server import mcp as server

SERVER_FILE = Path(__file__).with_name("order_server.py")


def tokens(text: str) -> int:
    """粗估 token：汉字按 1、其他按 0.25。只为比较量级，不是真实分词。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


def tool_cost(tool) -> int:
    """一个工具进上下文要付的 token：名字 + 说明 + 参数 schema。"""
    schema = json.dumps(tool.input_schema, ensure_ascii=False, sort_keys=True)
    return tokens(f"{tool.name}{tool.description or ''}{schema}")


async def main() -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
        print("=== 1. 工具清单 ===")
        total = 0
        for t in tools:
            cost = tool_cost(t)
            total += cost
            title = getattr(t.annotations, "title", None) if t.annotations else None
            print(f"  {t.name:14} 标题={title}  ~{cost} token")
        print(f"  {len(tools)} 个工具全量进上下文 ≈ {total} token")

        print("=== 2. 按需加载：只取本阶段要用的 ===")
        stage = {"get_order", "get_policy"}
        picked = [t for t in tools if t.name in stage]
        partial = sum(tool_cost(t) for t in picked)
        print(f"  本阶段只用 {sorted(x.name for x in picked)}，约 {partial} token")
        print(f"  省下的约 {total - partial} token：本阶段不发另外 4 个工具的 schema")

        print("=== 3. 调用工具 ===")
        order = await client.call_tool("get_order", {"order_id": "A1001"})
        print("  get_order ->", order.structured_content)
        policy = await client.call_tool("get_policy", {"category": "普通"})
        print("  get_policy ->", policy.structured_content)
        verdict = await client.call_tool(
            "review_refund", {"order_id": "A1001", "unopened": True}
        )
        print("  review_refund ->", verdict.structured_content)

        print("=== 4. 工具报错是数据，不是异常 ===")
        bad = await client.call_tool("get_order", {"order_id": "Z9999"}, raise_on_error=False)
        print("  is_error =", bad.is_error, "|", bad.content[0].text)

        print("=== 5. 资源：不占工具清单，按名读 ===")
        templates = await client.list_resource_templates()
        print("  资源模板：", [r.uri_template for r in templates])
        text = await client.read_resource("policy://refund/生鲜")
        print("  读到的条款：", text[0].text.replace("\n", " / "))

        print("=== 6. 提示词模板 ===")
        prompts = await client.list_prompts()
        print("  提示词：", [p.name for p in prompts])
        rendered = await client.get_prompt("review_flow", {"order_id": "A1001"})
        print("  渲染首行：", rendered.messages[0].content.text.splitlines()[0])

        print("=== 7. 子进程 stdio 的连法（本机没跑，见正文说明）===")
        print(f"  Client({SERVER_FILE.name!s})  # 由 client 拉起子进程，走 stdio")


if __name__ == "__main__":
    asyncio.run(main())

