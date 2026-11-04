"""能力层（SPEC M13.4.2）：文件五件套 / 沙箱两件 / 技能三件 + 结果截断。

**能力按 `spec.scopes` 经 `ToolContext` 注入**，工具自己不去找全局单例。
工具函数的第一个参数若标注为 `ToolContext`，框架在调用时注入它。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from harness.contracts.types import ToolContext, ToolResult
from harness.parts.middleware.base import Layer, layer
from harness.parts.tools import FunctionTool, ToolRegistry, tool


# ------------------------------------------------------------------ 文件五件套


def fs_tools() -> list[FunctionTool]:
    """全部走 `ctx.fs`（虚拟路径 + 挂载表，越界即拒）。"""

    @tool(side_effects="read", scopes={"fs:read"})
    async def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = 2000) -> str:
        """读取文件。

        Args:
            path: 虚拟路径，如 /work/a.txt
            offset: 起始行
            limit: 最多行数
        """
        raw = await ctx.fs.read(path)
        text = raw.decode("utf-8", "replace")
        lines = text.splitlines()
        return "\n".join(lines[offset : offset + limit])

    @tool(side_effects="write", scopes={"fs:write"})
    async def write_file(ctx: ToolContext, path: str, content: str) -> dict:
        """写入文件（覆盖）。"""
        await ctx.fs.write(path, content.encode("utf-8"))
        return {"ok": True, "bytes": len(content.encode("utf-8"))}

    @tool(side_effects="write", scopes={"fs:write"})
    async def edit_file(ctx: ToolContext, path: str, old: str, new: str, count: int = 1) -> dict:
        """按文本替换编辑文件。"""
        replaced = await ctx.fs.edit(path, old, new, count=count)
        return {"ok": True, "replaced": replaced}

    @tool(side_effects="read", scopes={"fs:read"})
    async def glob(ctx: ToolContext, pattern: str) -> list[str]:
        """按通配符列文件，如 /work/**/*.py。"""
        return await ctx.fs.glob(pattern)

    @tool(side_effects="read", scopes={"fs:read"})
    async def grep_path(ctx: ToolContext, pattern: str, glob: str = "**/*", max_hits: int = 200) -> list[dict]:
        """在文件内容里正则搜索。"""
        hits = await ctx.fs.grep(pattern, glob=glob, max_hits=max_hits)
        return [{"path": h.path, "line": h.line, "text": h.text} for h in hits]

    return [read_file, write_file, edit_file, glob, grep_path]


# ------------------------------------------------------------------ 沙箱两件


def sandbox_tools() -> list[FunctionTool]:
    """`exec` 只收 argv 列表，**绝不收字符串命令**；env 只接受密钥名。"""

    @tool(side_effects="shell", scopes={"sandbox:exec"}, timeout_s=60, sandbox=True)
    async def exec(ctx: ToolContext, argv: list[str], cwd: str = "/work",
                   timeout_s: int = 30, env_keys: list[str] = ()) -> dict:
        """在沙箱里执行命令（argv 列表）。

        Args:
            argv: 命令与参数，如 ["python", "-V"]
            cwd: 工作目录
            timeout_s: 超时秒数
            env_keys: 需要注入的环境变量名（只取名字，值不回流）
        """
        env = {name: await ctx.secrets.get(name) for name in env_keys}
        result = await ctx.sandbox.exec(
            argv, cwd=cwd, env=env, limits=None, timeout_s=timeout_s
        )
        return {
            "exit": result.exit,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "truncated": result.truncated,
        }

    @tool(side_effects="shell", scopes={"sandbox:exec"})
    async def kill(ctx: ToolContext, exec_id: str) -> dict:
        """终止一次沙箱执行（幂等）。"""
        await ctx.sandbox.kill(exec_id)
        return {"ok": True}

    return [exec, kill]


# ------------------------------------------------------------------ 技能三件


def skill_tools() -> list[FunctionTool]:
    """三段式披露的第 ②③ 段：正文与资源按需加载。"""

    @tool(side_effects="read")
    async def load_skill(ctx: ToolContext, name: str) -> str:
        """加载技能正文（第 ② 段）。"""
        skill = await ctx.skills.load(name)
        return getattr(skill, "body", str(skill))

    @tool(side_effects="read")
    async def read_skill_resource(ctx: ToolContext, name: str, path: str) -> str:
        """读取技能资源文件（第 ③ 段）。"""
        return await ctx.skills.resource(name, path)

    @tool(side_effects="read")
    async def list_skills(ctx: ToolContext) -> list[dict]:
        """列出可用技能（目录通常常驻，此工具用于显式列举）。"""
        return [
            {"name": m.name, "description": m.description}
            for m in ctx.skills.catalog()
        ]

    return [load_skill, read_skill_resource, list_skills]


# ------------------------------------------------------------------ 注册


def build_capability_tools(
    *,
    fs: bool = False,
    sandbox: bool = False,
    skills: bool = False,
) -> list[FunctionTool]:
    """按需组装三组工具（缺哪个后端就别开对应组）。"""
    tools: list[FunctionTool] = []
    if fs:
        tools += fs_tools()
    if sandbox:
        tools += sandbox_tools()
    if skills:
        tools += skill_tools()
    return tools


def register_capabilities(
    registry: ToolRegistry,
    *,
    fs: bool = False,
    sandbox: bool = False,
    skills: bool = False,
) -> ToolRegistry:
    return registry.add(*build_capability_tools(fs=fs, sandbox=sandbox, skills=skills))


# ------------------------------------------------------------------ 截断层


def truncate_layer(*, artifacts: Any, max_output_bytes: int = 32_000) -> Layer:
    """插点 tool_call：超长输出转工件，只回摘要（SPEC M13.4.2 共同约束）。"""

    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            result = getattr(response, "result", None)
            if not isinstance(result, ToolResult) or result.output is None:
                return response
            raw = result.output.encode("utf-8")
            if len(raw) <= max_output_bytes:
                return response
            ref = await artifacts.put(f"{result.tool or 'tool'}.txt", raw)
            summary = (
                f"[已截断] 原始 {len(raw)} 字节，已存为 {ref.uri}；"
                f"前 200 字：{result.output[:200]}"
            )
            return replace(
                response,
                result=replace(result, output=summary, artifacts=[*result.artifacts, ref]),
            )

        return handler

    return layer("truncate", ["tool_call"], build, needs=["artifacts"])


__all__ = [
    "fs_tools",
    "sandbox_tools",
    "skill_tools",
    "build_capability_tools",
    "register_capabilities",
    "truncate_layer",
]
