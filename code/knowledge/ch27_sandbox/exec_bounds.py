"""资源与时间边界：输出截断、超时终止、以及超时杀不到的孙进程。

运行：python code/knowledge/ch27_sandbox/exec_bounds.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent / ".demo-exec"


def cap_output(chunks, limit: int) -> tuple[str, bool, int]:
    """按字节截断工具输出。返回 (保留下来的文本, 是否截断, 原始总字节数)。"""
    buf = bytearray()
    total = 0
    truncated = False
    for c in chunks:
        raw = c.encode("utf-8")
        total += len(raw)
        if len(buf) >= limit:
            truncated = True
            continue
        room = limit - len(buf)
        if len(raw) > room:
            buf += raw[:room]
            truncated = True
        else:
            buf += raw
    # 截断点可能落在多字节字符中间，解码时丢掉半个字符
    return buf.decode("utf-8", "ignore"), truncated, total


def run_with_timeout(cmd: list[str], timeout_s: float) -> tuple[str, float]:
    """给一次外部调用加上时限。返回 (结果, 实际耗时)。"""
    t0 = time.perf_counter()
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
        return "正常结束", time.perf_counter() - t0
    except subprocess.TimeoutExpired:
        return "超时被中止", time.perf_counter() - t0


def grandchild_demo() -> None:
    """父进程被超时中止后，孙进程是否还活着。"""
    BASE.mkdir(exist_ok=True)

    outer = (
        "import subprocess, sys, time\n"
        "marker = sys.argv[1]\n"
        "inner = ('import pathlib, sys, time; time.sleep(2); "
        "pathlib.Path(sys.argv[1]).write_text(\"alive\", encoding=\"utf-8\")')\n"
        "subprocess.Popen([sys.executable, '-c', inner, marker])\n"
        "time.sleep(30)\n"
    )

    def once(tag: str, use_pipe: bool) -> None:
        marker = BASE / f"grandchild-{tag}.txt"
        marker.unlink(missing_ok=True)
        kwargs = (
            {"capture_output": True, "text": True}
            if use_pipe
            else {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        )
        t0 = time.perf_counter()
        try:
            subprocess.run(
                [sys.executable, "-c", outer, str(marker)], timeout=1.0, **kwargs
            )
            result = "正常结束"
        except subprocess.TimeoutExpired:
            result = "超时被中止"
        elapsed = time.perf_counter() - t0
        print(f"  stdio={'pipe' if use_pipe else 'devnull'}  {result}，函数耗时 {elapsed:.2f} 秒")
        time.sleep(1.2 if use_pipe else 2.5)
        print(f"    标记存在：{marker.exists()}（孙进程睡 2 秒后写）")
        marker.unlink(missing_ok=True)

    once("devnull", use_pipe=False)
    once("pipe", use_pipe=True)
    print("  <- 同样是 1 秒时限：pipe 那次被孙进程握着的管道拖到 2 秒才返回")
    print("     timeout 中止的是直接子进程；孙进程不在这一刀范围内")
    BASE.rmdir()


def main() -> None:
    print("=== 1. 输出上限 4096 字节 ===")
    text, truncated, total = cap_output(["x" * 2_000_000], 4096)
    print(f"  原始 {total} 字节，保留 {len(text.encode('utf-8'))} 字节，截断={truncated}")
    short, short_truncated, short_total = cap_output(["y" * 100], 4096)
    print(f"  短输出：原始 {short_total} 字节，保留 {len(short.encode('utf-8'))} 字节，截断={short_truncated}")

    print()
    print("=== 2. 时限 1 秒，子进程要睡 30 秒 ===")
    result, elapsed = run_with_timeout(
        [sys.executable, "-c", "import time; time.sleep(30)"], 1.0
    )
    print(f"  {result}，函数耗时 {elapsed:.2f} 秒")

    print()
    print("=== 3. 父进程被中止之后，孙进程还活着吗 ===")
    grandchild_demo()


if __name__ == "__main__":
    main()
