"""优雅关闭的时序，以及两种 CMD 写法为什么结果不同。

本机没有 docker，所以这里只做两件事：

  1 真的跑一遍进程内的 SIGTERM 处理：用 signal.raise_signal 把信号送进 handler，
    时间戳是实测的，演示"停止接收 -> 排空在途 -> 退出"的顺序。
  2 把两份 Dockerfile 的文本打印出来，并说明 shell 形态下预期的关闭行为。
    shell 形态与容器层的行为**没有在本机执行**，只给文本说明，不伪造运行结果。

运行：python code/knowledge/ch32_delivery/shutdown.py
"""

from __future__ import annotations

import signal
import threading
import time
from pathlib import Path

T0 = 0.0
SIGNAL_AT = 0.0
EVENTS: list[tuple[float, str]] = []
LOCK = threading.Lock()


def ms() -> float:
    return (time.perf_counter() - T0) * 1000


def note(text: str) -> None:
    with LOCK:
        EVENTS.append((ms(), text))


class Worker:
    """一次处理一条任务，每条 150ms；停止时把手上的与排队的都做完。"""

    def __init__(self, job_ms: int = 150) -> None:
        self.job_ms = job_ms
        self.queue: list[int] = []
        self.done: list[int] = []
        self.lost: list[int] = []
        self.in_flight: int | None = None
        self.stopping = threading.Event()
        self.dead = False
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def submit(self, job: int) -> None:
        self.queue.append(job)

    def start(self) -> None:
        self.thread.start()

    def _loop(self) -> None:
        while not self.dead:
            if self.stopping.is_set() and not self.queue:
                note("队列空、在途结束：worker 返回")
                return
            if not self.queue:
                time.sleep(0.002)
                continue
            job = self.queue.pop(0)
            self.in_flight = job
            note(f"开始执行 job-{job}（队列剩 {len(self.queue)}）")
            time.sleep(self.job_ms / 1000)
            self.done.append(job)
            self.in_flight = None
            note(f"job-{job} 完成并确认")

    def join(self, grace_s: float) -> bool:
        self.thread.join(timeout=grace_s)
        return not self.thread.is_alive()


def run_exec_form() -> None:
    global T0, SIGNAL_AT
    EVENTS.clear()
    T0 = time.perf_counter()
    worker = Worker()
    for job in range(1, 6):
        worker.submit(job)
    worker.start()
    time.sleep(0.06)                     # 让 job-1 进入在途

    def on_term(signum: int, frame) -> None:
        global SIGNAL_AT
        SIGNAL_AT = ms()
        note("SIGTERM 到达 handler（PID 1 是 python，信号直达）")
        worker.stopping.set()
        note("置 stopping：入口开始返回 503，不再接收新请求")

    previous = signal.signal(signal.SIGTERM, on_term)
    signal.raise_signal(signal.SIGTERM)  # 模拟 docker stop 发出的 SIGTERM
    note("主线程进入排空等待")

    if not worker.join(grace_s=2.0):
        worker.dead = True
        note("grace 用尽：SIGKILL 之前仍有任务未完成")
    else:
        note(f"排空完成：完成 {len(worker.done)} 条，丢失 {len(worker.lost)} 条")
    signal.signal(signal.SIGTERM, previous)

    print("=== 1. exec 形态：SIGTERM 下的关闭时序 ===")
    for t, text in EVENTS:
        rel = t - SIGNAL_AT
        print(f"  t{rel:+7.1f}ms  {text}")
    print("  注：信号是进程内 raise 的，时间戳为实测；未在本机执行 docker")


def show_shell_expected() -> None:
    print()
    print("=== 2. shell 形态：预期行为（未在本机执行 docker）===")
    print("  Dockerfile: CMD python -u app.py")
    print("  实际 argv:  /bin/sh -c \"python -u app.py\"")
    print("  PID 1 = /bin/sh；SIGTERM 只到 sh，sh 不转发给 python")
    print("  t+0ms       docker stop 发 SIGTERM")
    print("  t+0ms       sh 收到信号，python 不知道，继续处理 job-1")
    print("  t+10000ms   docker 发 SIGKILL，python 与在途任务一起消失")
    print("  预期：在途 1 条与排队 4 条全部丢失，且没有关闭日志")
    print("  以上是文本推演，不是本机运行结果")


def show_dockerfiles() -> None:
    here = Path(__file__).resolve().parent
    print()
    print("=== 3. 两份 Dockerfile 的对照 ===")
    for name, label in (("Dockerfile.exec", "exec 形态"), ("Dockerfile.shell", "shell 形态")):
        print(f"--- {label}: {name} ---")
        print((here / name).read_text(encoding="utf-8").rstrip())
    print()
    print("  写法        PID 1        SIGTERM 去向            关闭结果")
    print("  exec        python       直达 python             排空后退出")
    print("  shell       /bin/sh      停在 sh，不转发          grace 结束被 SIGKILL")


def main() -> None:
    run_exec_form()
    show_shell_expected()
    show_dockerfiles()


if __name__ == "__main__":
    main()
