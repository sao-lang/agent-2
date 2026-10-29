"""四条边界挂在同一个入口上：同一批调用分别被谁拦下。

运行：python code/knowledge/ch27_sandbox/bounded_tool.py
网络判定用注入的解析表，不发真实请求；时间边界会真的中止一个子进程。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from exec_bounds import cap_output
from network_bounds import check_url

BASE = Path(__file__).resolve().parent / ".demo-tool"
ROOT = BASE / "workspace"
OUTPUT_LIMIT = 4096
TIMEOUT_S = 1.0


def read_file(user_path: str) -> dict:
    try:
        target = (ROOT / user_path).resolve()
    except (OSError, RuntimeError):
        return {"ok": False, "boundary": "path", "reason": "路径无法解析"}
    if not target.is_relative_to(ROOT):
        return {"ok": False, "boundary": "path", "reason": f"路径越界：{target}"}
    if not target.is_file():
        return {"ok": False, "boundary": "path", "reason": f"不是文件：{target}"}
    text = target.read_text(encoding="utf-8")
    return {"ok": True, "chars": len(text)}


def fetch(url: str) -> dict:
    why = check_url(url)
    if why:
        return {"ok": False, "boundary": "network", "reason": why}
    return {"ok": True, "bytes": 0, "note": "示例不发真实请求"}


def run(cmd: list[str]) -> dict:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "boundary": "time", "reason": f"超过 {TIMEOUT_S} 秒上限"}
    text, truncated, total = cap_output([proc.stdout], OUTPUT_LIMIT)
    result = {"ok": True, "bytes": len(text.encode("utf-8")), "truncated": truncated}
    if truncated:
        result["note"] = f"原始 {total} 字节，只保留前 {OUTPUT_LIMIT} 字节"
    return result


def main() -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    (ROOT / "sub").mkdir(parents=True)
    (ROOT / "notes.txt").write_text("界内笔记", encoding="utf-8")
    (BASE / "outside").mkdir()

    spam = [
        sys.executable,
        "-c",
        "for _ in range(20000): print('x' * 100)",
    ]
    calls = [
        ("读 notes.txt", lambda: read_file("notes.txt")),
        ("读 ../outside/secret.txt", lambda: read_file("../outside/secret.txt")),
        ("读 /etc/passwd", lambda: read_file("/etc/passwd")),
        ("取元数据地址", lambda: fetch("https://169.254.169.254/latest/meta-data/")),
        ("取白名单域名", lambda: fetch("https://api.example.com/v1/orders")),
        ("跑一个刷屏命令", lambda: run(spam)),
        (
            "跑一个睡 5 秒的命令",
            lambda: run([sys.executable, "-c", "import time; time.sleep(5)"]),
        ),
    ]

    print("=== 1. 七次调用，分别被哪条边界处理 ===")
    counts: dict[str, int] = {}
    for label, call in calls:
        result = call()
        if result["ok"]:
            key = "resource(截断)" if result.get("truncated") else "pass"
            print(f"  {label}")
            print(f"    放行 {result}")
        else:
            key = result["boundary"]
            print(f"  {label}")
            print(f"    拒绝[{key}] {result['reason']}")
        counts[key] = counts.get(key, 0) + 1

    print()
    print("=== 2. 汇总 ===")
    print(f"  {counts}")
    print("  <- 放行的三次：一次正常读、一次正常取数、一次被截断但继续")
    print("     拒绝的四种原因都是结构化返回，循环拿到原因后可以换参数再试")
    shutil.rmtree(BASE, ignore_errors=True)


if __name__ == "__main__":
    main()
