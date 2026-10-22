#!/usr/bin/env python
"""第 34 章：Docker 沙箱执行器（真实隔离版）。

前置条件：本机装了 Docker，且能拉 alpine 镜像。

用法：
    python code/ch33_sandbox/shell_sandbox.py "python -c 'print(1+1)'"

安全要点（每一条都对应一个真实的逃逸场景）：
  1. --network none        断网（防数据外泄 / SSRF）
  2. --read-only           根文件系统只读（防写入系统目录）
  3. -v <workdir>:/work    只挂一个工作目录（防读宿主机其他文件）
  4. --memory / --cpus     限制资源（防 fork 炸弹 / 挖矿）
  5. --pids-limit          限制进程数（fork 炸弹）
  6. --cap-drop ALL        去掉所有 Linux capabilities
  7. --security-opt no-new-privileges  禁止提权
  8. --user                非 root 运行
  9. timeout               外层兜底（防止卡死）
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

IMAGE = "python:3.12-alpine"


def run_in_sandbox(cmd: str, timeout: int = 20, workdir: Path | None = None) -> dict:
    if shutil.which("docker") is None:
        return {"ok": False, "error": "未找到 docker 命令，请先安装 Docker Desktop"}

    workdir = workdir or Path(tempfile.mkdtemp(prefix="agentwork_"))
    workdir.mkdir(parents=True, exist_ok=True)
    name = f"agent-sbx-{uuid.uuid4().hex[:8]}"

    args = [
        "docker", "run", "--rm",
        "--name", name,
        "--network", "none",                       # 断网
        "--read-only",                             # 根文件系统只读
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "-v", f"{workdir.resolve()}:/work",        # 只挂工作目录
        "-w", "/work",
        "--user", "65534:65534",                   # nobody
        "--memory", "256m",
        "--cpus", "0.5",
        "--pids-limit", "128",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        IMAGE,
        "sh", "-lc", cmd,
    ]

    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": p.stdout[-4000:],
            "stderr": p.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        # 超时要显式 kill，--rm 才会生效
        subprocess.run(["docker", "kill", name], capture_output=True)
        return {"ok": False, "error": f"超时（>{timeout}s），容器已终止"}


def demo() -> None:
    cases = [
        ("echo hello && ls /", "基本执行 + 看根目录"),
        ("cat /etc/passwd | head -2", "可以读，但只是容器里的"),
        ("touch /root/x", "写系统目录应失败（read-only）"),
        ("curl -s https://example.com -m 3 || echo NO_NET", "应该断网"),
        ("ls /work", "只有工作目录可见"),
        ("python -c \"print(sum(range(100)))\"", "在容器里跑 python"),
    ]
    for cmd, label in cases:
        print(f"\n$ {cmd}    # {label}")
        r = run_in_sandbox(cmd)
        if r.get("stdout"):
            print("  stdout:", r["stdout"].strip()[:300])
        if r.get("stderr"):
            print("  stderr:", r["stderr"].strip()[:300])
        if r.get("error"):
            print("  error :", r["error"])
        print("  ok:", r["ok"])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(run_in_sandbox(" ".join(sys.argv[1:])))
    else:
        demo()
