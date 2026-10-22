"""第 20 章产出：沙箱与工具边界（不依赖 Docker 也能跑教学版）。

真实沙箱用 Docker / Firecracker / gVisor。本章的重点不是"怎么起容器"，
而是**边界的四个维度**：
  1. 文件系统：只能访问授权目录
  2. 网络：默认断网，白名单放行
  3. 资源：CPU / 内存 / 时间上限
  4. 审计：每个动作都留痕

本文件提供一个**进程内可验证**的策略引擎，让你能对"越界"写单元测试；
同时给出一份可直接用的 Docker 沙箱脚本（在 shell_sandbox.py 里）。
"""
from __future__ import annotations

import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================ 动作分类

class ActionKind:
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NET = "net"


@dataclass
class SandboxPolicy:
    """沙箱策略：默认全部禁止，逐项放行。

    为什么用"白名单"而不是"黑名单"？
    因为黑名单永远不完备：你列了 rm -rf，攻击者用 `find . -delete`；
    你列了 curl，攻击者用 `wget`、`python -c`、`nc`、`/dev/tcp`。
    """

    workdir: Path = field(default_factory=lambda: Path.cwd() / "sandbox")
    read_allow: list[Path] = field(default_factory=list)
    write_allow: list[Path] = field(default_factory=list)
    net_allow: list[str] = field(default_factory=list)     # 域名白名单
    max_seconds: float = 30.0
    max_output_bytes: int = 64_000
    allow_exec: bool = False                                # 默认不允许执行命令
    default_deny_net: bool = True                           # 默认断网（白名单为空也不放行）

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir).resolve()
        if not self.read_allow:
            self.read_allow = [self.workdir]
        if not self.write_allow:
            self.write_allow = [self.workdir]


# ============================================================ 路径检查

def _is_within(path: Path, roots: list[Path]) -> bool:
    try:
        p = path.resolve()
    except (OSError, RuntimeError):
        return False
    for r in roots:
        try:
            p.relative_to(Path(r).resolve())
            return True
        except ValueError:
            continue
    return False


def check_path(path: str, policy: SandboxPolicy, mode: str = "read") -> tuple[bool, str]:
    """文件系统边界检查。

    必须处理的三类绕过：
      1. ../ 穿越：../../etc/passwd
      2. 符号链接：ln -s /etc ./etc-link
      3. 绝对路径：/etc/shadow

    ⚠️ 关键：用 resolve() 而不是字符串检查——
       `./x/../../etc/passwd` 字符串里不含 `..` 吗？含。
       但 `./a/b/../../../etc` 这种，简单的 startswith 检查会漏。
    """
    p = Path(path)
    roots = policy.read_allow if mode == "read" else policy.write_allow

    if not p.is_absolute():
        p = policy.workdir / p

    # resolve() 会展开符号链接和 ..
    resolved = p.resolve()

    if not _is_within(resolved, roots):
        return False, f"拒绝访问：{resolved} 不在授权范围内 {[str(r) for r in roots]}"

    # 额外的"软链接指向外部"检查（resolve 已处理，但保留显式提示）
    if p.exists() and p.is_symlink() and not _is_within(Path(os.path.realpath(p)), roots):
        return False, f"拒绝访问：符号链接指向外部 {os.path.realpath(p)}"

    return True, str(resolved)


def check_command(cmd: str, policy: SandboxPolicy) -> tuple[bool, str]:
    """命令检查（白名单 + 结构检查）。

    ⚠️ 这一层永远不够安全。真正的隔离必须靠容器 + 只读挂载 + 断网。
       本函数的作用是"挡住明显的错误"，不是"防住有意的攻击"。
    """
    if not policy.allow_exec:
        return False, "策略禁止执行命令"

    # 结构检查：管道、重定向、命令替换 —— 都可能导致越界
    dangerous_structure = ["|", ">", "<", "$(", "`", "&&", "||", ";", "&"]
    for s in dangerous_structure:
        if s in cmd:
            return False, f"命令包含不允许的结构：{s}"

    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return False, f"命令解析失败：{e}"
    if not parts:
        return False, "空命令"

    allowed_cmds = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "git", "python", "pytest"}
    if parts[0] not in allowed_cmds:
        return False, f"命令 {parts[0]} 不在白名单"

    # 参数里的绝对路径也要检查
    for arg in parts[1:]:
        if arg.startswith("/") and arg not in ("/dev/null",):
            ok, why = check_path(arg, policy, "read")
            if not ok:
                return False, why

    return True, "ok"


def check_url(url: str, policy: SandboxPolicy) -> tuple[bool, str]:
    """网络边界：域名白名单 + 禁止私网地址。

    为什么要禁私网？
    因为 Agent 可能被诱导访问 http://169.254.169.254/（云元数据接口），
    拿到云主机的临时凭证——这是真实的攻击路径。
    """
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return False, "非法 URL"

    host = m.group(1).split(":")[0].lower()

    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return False, "禁止访问本机地址"
    if host.startswith("169.254.") or host.startswith("10.") or host.startswith("192.168."):
        return False, "禁止访问私网/元数据地址"
    if re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host):
        return False, "禁止访问私网地址"

    if not policy.net_allow:
        if policy.default_deny_net:
            return False, "默认断网：未配置网络白名单"
    elif not any(host == d or host.endswith("." + d) for d in policy.net_allow):
        return False, f"域名 {host} 不在白名单 {policy.net_allow}"

    return True, "ok"


# ============================================================ 审计日志

@dataclass
class AuditLog:
    """审计日志：谁、何时、对什么、做了什么、结果如何。

    一条好的审计记录必须能回答：
      "3 月 5 日 14:23，用户 A 的 Agent 试图写 /etc/passwd，被拒绝"
    """

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, kind: str, target: str, allowed: bool, reason: str, meta: dict | None = None) -> None:
        self.entries.append({
            "ts": time.time(),
            "kind": kind,
            "target": target,
            "allowed": allowed,
            "reason": reason,
            **(meta or {}),
        })

    def denied(self) -> list[dict[str, Any]]:
        return [e for e in self.entries if not e["allowed"]]

    def summary(self) -> dict[str, Any]:
        total = len(self.entries)
        denied = len(self.denied())
        by_kind: dict[str, int] = {}
        for e in self.denied():
            by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
        return {"total": total, "denied": denied, "denied_by_kind": by_kind}


# ============================================================ 统一入口

@dataclass
class Sandbox:
    policy: SandboxPolicy = field(default_factory=SandboxPolicy)
    audit: AuditLog = field(default_factory=AuditLog)

    def read_file(self, path: str) -> str:
        ok, detail = check_path(path, self.policy, "read")
        self.audit.record(ActionKind.READ, path, ok, detail)
        if not ok:
            raise PermissionError(detail)
        text = Path(detail).read_text(encoding="utf-8", errors="replace")
        if len(text.encode()) > self.policy.max_output_bytes:
            text = text[: self.policy.max_output_bytes]
        return text

    def write_file(self, path: str, content: str) -> str:
        ok, detail = check_path(path, self.policy, "write")
        self.audit.record(ActionKind.WRITE, path, ok, detail)
        if not ok:
            raise PermissionError(detail)
        p = Path(detail)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return detail

    def run(self, cmd: str) -> str:
        ok, detail = check_command(cmd, self.policy)
        self.audit.record(ActionKind.EXEC, cmd, ok, detail)
        if not ok:
            raise PermissionError(detail)
        # 教学版：不真的执行（真实实现见 shell_sandbox.py 的 Docker 版本）
        return f"[模拟执行] {cmd}"

    def fetch(self, url: str) -> str:
        ok, detail = check_url(url, self.policy)
        self.audit.record(ActionKind.NET, url, ok, detail)
        if not ok:
            raise PermissionError(detail)
        return f"[模拟请求] {url}"
