"""最小 MCP server、工具命名空间前缀、Skill 三级加载的量。

不联网。MCP server 用 stdin/stdout 跑 JSON-RPC，客户端直接喂一行请求。
Skill 的目录树在临时目录里生成，用来对比 L1/L2/L3 的加载量。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "mini_mcp_server.py")


# ---------------------------------------------------------------- 1. MCP 往返

def mcp_roundtrip(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    """起一个 server 进程，写一行请求，读最后一行响应。"""
    req = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
    proc = subprocess.run(
        [sys.executable, SERVER],
        input=json.dumps(req, ensure_ascii=False) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    lines = (proc.stdout or "").strip().splitlines()
    return json.loads(lines[-1]) if lines else {"error": "no output", "stderr": proc.stderr}


# ---------------------------------------------------------------- 2. 前缀

def namespaced(server: str, tool: str) -> str:
    """外部工具进模型可见清单时加前缀，避免与本地工具撞名。"""
    return f"{server}__{tool}"


# ---------------------------------------------------------------- 3. Skill 目录

def build_skill(root: str) -> None:
    for sub in ("references", "scripts", "templates"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    with open(os.path.join(root, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(
            "---\n"
            "name: refund-review\n"
            "description: 处理电商退货审查。当用户询问订单能否退货、需要核对政策与签收天数时使用。\n"
            "---\n\n"
            "# 退货审查\n\n"
            "1. 取订单签收天数\n2. 取政策窗口\n3. 比对并给出结论\n"
        )
    with open(os.path.join(root, "references", "policy.md"), "w", encoding="utf-8") as f:
        f.write("政策全文……\n" * 200)
    with open(os.path.join(root, "scripts", "check.py"), "w", encoding="utf-8") as f:
        f.write("print('check ok')\n")
    with open(os.path.join(root, "templates", "reply.md"), "w", encoding="utf-8") as f:
        f.write("模板……\n" * 50)


def meta_only(root: str) -> int:
    """L1：只读 SKILL.md 的 frontmatter（name + description）。"""
    text = open(os.path.join(root, "SKILL.md"), encoding="utf-8").read()
    end = text.find("\n---", 4)
    return len(text[: end + 4]) if end != -1 else len(text)


def skill_body(root: str) -> int:
    """L2：frontmatter + 正文。"""
    return os.path.getsize(os.path.join(root, "SKILL.md"))


def all_files(root: str) -> int:
    """L1+L2+L3：整棵目录。"""
    return sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, _, fns in os.walk(root)
        for fn in fns
    )


def main() -> None:
    print("=== 1. MCP 初始化 ===")
    print(json.dumps(mcp_roundtrip("initialize"), ensure_ascii=False, indent=2))

    print()
    print("=== 2. 列出工具（加前缀后进清单）===")
    tools = mcp_roundtrip("tools/list", msg_id=2).get("result", {}).get("tools", [])
    for t in tools:
        print(f"  {namespaced('order', t['name'])}  <- {t['description']}")

    print()
    print("=== 3. 调用工具 ===")
    call = mcp_roundtrip(
        "tools/call", {"name": "get_order", "arguments": {"order_id": "A1001"}}, msg_id=3
    )
    print(" ", json.dumps(call, ensure_ascii=False))

    print()
    print("=== 4. 未声明的工具（默认拒绝）===")
    bad = mcp_roundtrip("tools/call", {"name": "drop_table", "arguments": {}}, msg_id=4)
    print(" ", json.dumps(bad, ensure_ascii=False))

    print()
    print("=== 5. Skill 三级加载的量 ===")
    with tempfile.TemporaryDirectory() as d:
        build_skill(d)
        l1, l2, l3 = meta_only(d), skill_body(d), all_files(d)
        print(f"  L1 只读元数据:   {l1} 字符")
        print(f"  L2 加正文:       {l2} 字符")
        print(f"  L3 含资源:       {l3} 字符")
        print(f"  L3 / L1 = {l3 / l1:.0f} 倍")


if __name__ == "__main__":
    main()
