"""资源与时间边界：工具能花多少、能跑多久。

不联网。三组演示都是真的在跑：
  1. 输出上限：造 2MB 的输出，看截断点停在哪
  2. 执行时限：subprocess 的 timeout 真的把子进程中止
  3. 超时之后，它启动的孙进程还在不在（这一条是边界最常见的漏）
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

WORK = Path("_exec_demo").resolve()

# 子进程：先启动一个孙进程（3 秒后写标记文件），然后自己睡 30 秒。
# 第二个参数决定孙进程的 stdio 是继承父进程的管道，还是指向 DEVNULL。
CHILD_SRC = '''\
import subprocess, sys, time

marker, mode = sys.argv[1], sys.argv[2]
gc = (
    "import pathlib, sys, time; "
    "time.sleep(3); "
    "pathlib.Path(sys.argv[1]).write_text('孙进程写下了这一行', encoding='utf-8')"
)
kw = {}
if mode == "devnull":
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
subprocess.Popen([sys.executable, "-c", gc, marker], **kw)
time.sleep(30)
'''


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


def endless_lines(line: str, n: int):
    for _ in range(n):
        yield line


def run_with_timeout(cmd: list[str], timeout_s: float) -> tuple[str, float]:
    """给一次外部调用加上时限。返回 (结果, 实际耗时)。"""
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return f"正常结束，返回码 {r.returncode}", time.perf_counter() - t0
    except subprocess.TimeoutExpired:
        return "超时被中止", time.perf_counter() - t0


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()

    print("=== 1. 输出上限 4096 字节 ===")
    text, truncated, total = cap_output(endless_lines("x" * 99 + "\n", 20000), 4096)
    print(f"  原始 {total} 字节，保留 {len(text.encode('utf-8'))} 字节，截断={truncated}")
    text, truncated, total = cap_output(endless_lines("y" * 9 + "\n", 10), 4096)
    print(f"  短输出：原始 {total} 字节，保留 {len(text.encode('utf-8'))} 字节，截断={truncated}")

    print()
    print("=== 2. 时限都是 1 秒，子进程都要睡 30 秒 ===")
    child = WORK / "child.py"
    child.write_text(CHILD_SRC, encoding="utf-8")
    t_start = time.perf_counter()
    for mode in ("pipe", "devnull"):
        marker = WORK / f"grandchild_{mode}.txt"
        result, cost = run_with_timeout(
            [sys.executable, str(child), str(marker), mode], 1.0
        )
        print(f"  孙进程 stdio={mode:<8} {result}，函数返回耗时 {cost:.2f} 秒")
    print("  <- 同样是 1 秒的时限，第二次 1 秒就返回，第一次被拖到 3 秒：")
    print("     孙进程继承了管道，communicate() 要等管道关闭才能读到 EOF")

    print()
    print("=== 3. 父进程被中止之后，孙进程还活着吗 ===")
    time.sleep(3.2)
    for mode in ("pipe", "devnull"):
        marker = WORK / f"grandchild_{mode}.txt"
        elapsed = time.perf_counter() - t_start
        print(f"  t={elapsed:.1f}s  {mode:<8} 标记文件存在={marker.exists()}")
    print("  <- 两次的孙进程都活到了写文件那一刻；timeout 中止的只是直接子进程")

    shutil.rmtree(WORK)


if __name__ == "__main__":
    main()
