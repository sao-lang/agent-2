"""同一份 server，两种传输各连一次：streamable-http 与 sse。

跑法：python code/knowledge/ch26_mcp/transport_demo.py
说明：本机没装 pywin32，stdio 那条路（Host 拉起子进程）跑不通，示例只演示 URL 传输；
      换成 Client("order_server.py") 就是 stdio，工具定义与调用代码一行不改。
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from fastmcp import Client

# 本地地址必须绕过系统代理，否则请求会被代理转走（表现为 502）
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

SERVER = Path(__file__).with_name("order_server.py")


def wait_port(port: int, timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def start(transport: str, port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), "--transport", transport, "--port", str(port), "--no-banner"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


async def use(url: str, label: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        res = await client.call_tool("review_refund", {"order_id": "A1002", "unopened": True})
        print(f"  {label:16} URL={url}")
        print(f"  {'':16} 工具 {len(tools)} 个：{', '.join(t.name for t in tools)}")
        print(f"  {'':16} 调用结果：{res.structured_content['conclusion']} / {res.structured_content['clause']}")


async def main() -> None:
    print("=== 1. streamable-http：独立进程 + URL ===")
    proc = start("http", 8765)
    try:
        print("  服务已监听：", wait_port(8765))
        await use("http://127.0.0.1:8765/mcp", "http")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print("=== 2. sse：老式 Server-Sent Events 传输 ===")
    proc = start("sse", 8766)
    try:
        print("  服务已监听：", wait_port(8766))
        await use("http://127.0.0.1:8766/sse", "sse")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print("=== 3. 另外两种连法（不在本机跑） ===")
    print("  进程内：Client(server)                       # 单元测试用，不起进程")
    print("  stdio ：Client('code/knowledge/ch26_mcp/order_server.py')  # Host 拉起子进程")


if __name__ == "__main__":
    asyncio.run(main())
