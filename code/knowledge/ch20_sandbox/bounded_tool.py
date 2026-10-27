"""四条边界装在一个工具入口上：同一批调用，看谁先把它拦下来。

不联网。工具的每个动作都要过检查：
  路径  读写只能在 ROOT 之下
  网络  只允许 https + 白名单域名，且不接受字面 IP
  资源  单次输出上限 4096 字节
  时间  单次执行上限 1 秒

拒绝不是抛异常，而是返回结构化结果：调用方（循环）拿到 false 与原因，
可以把原因回灌给模型换一种做法，而不是整轮崩掉。
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path("_tool_demo").resolve()
MAX_OUTPUT = 4096
MAX_SECONDS = 1.0
ALLOWED_HOST_SUFFIX = ".example.com"


def _refuse(boundary: str, reason: str) -> dict:
    return {"ok": False, "boundary": boundary, "reason": reason}


def _display(path: Path) -> str:
    """错误信息里不出现家目录：界外的显示成 ../x，界内的显示成 x。"""
    try:
        rel = path.relative_to(ROOT.parent)
    except ValueError:
        return str(path)
    text = rel.as_posix()
    return text if text.startswith(ROOT.name + "/") else "../" + text


def _pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def resolve_path(user_path: str) -> Path:
    full = (ROOT / user_path).resolve()
    if not full.is_relative_to(ROOT):          # 路径边界
        raise PermissionError(f"路径越界：{_display(full)}")
    return full


def read_file(user_path: str) -> dict:
    try:
        p = resolve_path(user_path)
    except PermissionError as e:
        return _refuse("path", str(e))
    if not p.is_file():
        return _refuse("io", f"不是文件：{user_path}")
    return {"ok": True, "chars": len(p.read_text(encoding="utf-8"))}


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":                # 网络边界
        raise PermissionError(f"协议不允许：{parts.scheme}")
    if "@" in parts.netloc:
        raise PermissionError("netloc 含 userinfo")
    host = parts.hostname or ""
    try:                                       # 字面 IP 一律不接受
        ipaddress.ip_address(host)
        raise PermissionError(f"不接受字面 IP：{host}")
    except ValueError:
        pass
    if not host.endswith(ALLOWED_HOST_SUFFIX):
        raise PermissionError(f"域名不在白名单：{host}")


def fetch(url: str) -> dict:
    try:
        check_url(url)
    except PermissionError as e:
        return _refuse("network", str(e))
    return {"ok": True, "bytes": 0, "note": "示例不发真实请求"}


def run(cmd: list[str]) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=MAX_SECONDS)
    except subprocess.TimeoutExpired as e:      # 时间边界
        return _refuse("time", f"超过 {MAX_SECONDS} 秒上限")
    out = r.stdout
    if len(out) > MAX_OUTPUT:                   # 资源边界
        return {"ok": True, "bytes": MAX_OUTPUT, "truncated": True,
                "note": f"原始 {len(out)} 字节，只保留前 {MAX_OUTPUT} 字节"}
    return {"ok": True, "bytes": len(out), "truncated": False}


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir()
    (ROOT / "notes.txt").write_text("工作区内的文件", encoding="utf-8")

    calls = [
        ("读 notes.txt", lambda: read_file("notes.txt")),
        ("读 ../outside/secret", lambda: read_file("../outside/secret.txt")),
        ("读 /etc/passwd", lambda: read_file("/etc/passwd")),
        ("取元数据地址", lambda: fetch("https://169.254.169.254/latest/meta-data/")),
        ("取白名单域名", lambda: fetch("https://api.example.com/v1")),
        ("跑一个刷屏命令", lambda: run([sys.executable, "-c",
                                       "for _ in range(20000): print('x' * 99)"])),
        ("跑一个睡 5 秒的命令", lambda: run([sys.executable, "-c",
                                          "import time; time.sleep(5)"])),
    ]

    print("=== 1. 七次调用，分别被哪条边界处理 ===")
    for label, fn in calls:
        r = fn()
        tag = "放行" if r["ok"] else f"拒绝[{r['boundary']}] {r['reason']}"
        print(f"  {_pad(label, 22)} {tag}")
        if r["ok"]:
            print(f"  {'':22} {json.dumps(r, ensure_ascii=False)}")

    print()
    print("=== 2. 汇总 ===")
    counts: dict[str, int] = {}
    for _, fn in calls:
        r = fn()
        if not r["ok"]:
            key = r["boundary"]
        elif r.get("truncated"):
            key = "resource(截断)"
        else:
            key = "pass"
        counts[key] = counts.get(key, 0) + 1
    print(f"  {counts}")
    print("  <- 放行的三次：一次正常读、一次正常取数、一次被截断但继续")
    print("     拒绝的四种原因都是结构化返回，循环拿到原因后可以换参数再试")

    shutil.rmtree(ROOT)


if __name__ == "__main__":
    main()
