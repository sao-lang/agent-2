"""容器化的两件事：优雅关闭与镜像体积。

不联网，不用 docker。两段都是原理演示，但数字都是在本机跑出来的：

  1 优雅关闭：一个 worker 手上有在途任务，收到停止信号后"排空"还是"直接退出"，
    结果差别是几条任务丢失。exec 形态下信号直达进程，shell 形态下被 /bin/sh 吃掉。
  2 镜像体积：用两棵目录树模拟"单阶段构建"与"多阶段构建"的层内容，再统计字节数。
    目录结构是示意的，体积是真实测的。

注意：Windows 上的信号语义与 Linux 不同，所以这里的"收到信号"用一次函数调用
代替，只演示进程内的处理逻辑。
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

WORK = Path("_deliver_demo").resolve()


class Worker:
    """有在途任务的 worker。stop() 会排空，kill() 不会。"""

    def __init__(self, job_ms: int = 120) -> None:
        self.job_ms = job_ms
        self.queue: list[int] = []
        self.done: list[int] = []
        self.lost: list[int] = []
        self.in_flight: int | None = None
        self.dead = False
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def submit(self, job: int) -> None:
        self.queue.append(job)

    def start(self) -> None:
        self.thread.start()

    def _loop(self) -> None:
        while not self.dead:
            if self.stopping.is_set() and not self.queue:
                return
            if not self.queue:
                time.sleep(0.005)
                continue
            job = self.queue.pop(0)
            self.in_flight = job
            time.sleep(self.job_ms / 1000)
            if self.dead:                      # 进程已经没了，不该记完成
                return
            self.done.append(job)
            self.in_flight = None

    def stop(self, grace_ms: int) -> str:
        """exec 形态：信号直达进程，排空在途任务。"""
        self.stopping.set()
        self.thread.join(timeout=grace_ms / 1000)
        if self.thread.is_alive():
            self.lost.extend(self.queue)
            return f"grace {grace_ms}ms 用尽，仍有 {len(self.queue)} 条未完成"
        return f"排空完成，已完成 {len(self.done)} 条"

    def kill(self) -> str:
        """shell 形态：信号给了 sh，python 被直接杀掉。"""
        self.dead = True
        if self.in_flight is not None:
            self.lost.append(self.in_flight)
            self.in_flight = None
        self.lost.extend(self.queue)
        self.queue.clear()
        return f"进程被直接杀掉，丢失 {len(self.lost)} 条"


def run_shutdown_case(mode: str) -> None:
    w = Worker()
    for j in range(1, 5):
        w.submit(j)
    w.start()
    time.sleep(0.05)                       # 让它开始处理第 1 条
    msg = w.stop(grace_ms=800) if mode == "exec" else w.kill()
    print(f"  {mode:<5} {msg}")
    print(f"        完成 {sorted(w.done)}，丢失 {sorted(w.lost)}")


def build_image(tree: Path, files: dict[str, int]) -> tuple[int, int]:
    """按给定的文件大小造目录树，返回 (字节数, 文件数)。"""
    total = n = 0
    for rel, size in files.items():
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * size)
        total += size
        n += 1
    return total, n


BUILDER_ONLY = {
    **{f"build/compiler/part{i}.so": 1_000_000 for i in range(20)},
    **{f"build/headers/h{i}.h": 40_000 for i in range(30)},
    **{f"root/.cache/pip/w{i}.whl": 800_000 for i in range(8)},
}
RUNTIME = {
    "app/main.py": 8_000,
    "app/agent/loop.py": 12_000,
    "app/agent/tools.py": 9_000,
    "app/agent/guard.py": 7_000,
    **{f"venv/lib/pkg{i}.py": 300_000 for i in range(60)},
}


def mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()

    print("=== 1. 两种 Dockerfile 关闭行为的差别 ===")
    run_shutdown_case("exec")
    run_shutdown_case("shell")
    print("  <- 差别不在代码，在 CMD 的写法：exec 形态下 python 是 PID 1，直接收信号")

    print()
    print("=== 2. 两种 CMD 写法 ===")
    print("  exec 形态   CMD [\"python\", \"-u\", \"main.py\"]   -> 信号直达 python")
    print("  shell 形态  CMD python -u main.py              -> 实际是 /bin/sh -c ...")
    print("              信号给了 sh，sh 不转发，python 被 SIGKILL")

    print()
    print("=== 3. 单阶段与多阶段的层内容 ===")
    single, n_single = build_image(WORK / "single", {**BUILDER_ONLY, **RUNTIME})
    multi, n_multi = build_image(WORK / "multi", RUNTIME)
    builder_only = sum(BUILDER_ONLY.values())
    print(f"  单阶段：{n_single} 个文件，{mb(single)}")
    print(f"  多阶段：{n_multi} 个文件，{mb(multi)}")
    print(f"  差额 {mb(single - multi)}，全是只在构建期需要的东西：")
    print(f"    编译器 {mb(sum(v for k, v in BUILDER_ONLY.items() if 'compiler' in k))}"
          f"，头文件 {mb(sum(v for k, v in BUILDER_ONLY.items() if 'headers' in k))}"
          f"，pip 缓存 {mb(sum(v for k, v in BUILDER_ONLY.items() if 'cache' in k))}")
    print(f"  体积比 {single / multi:.1f} 倍（其中 {mb(builder_only)} 属于绝不该进镜像的那类）")

    print()
    print("=== 4. 拉取时间（按 100MB/s 粗算，仅示意）===")
    for label, size in (("单阶段", single), ("多阶段", multi)):
        print(f"  {label} {mb(size):>8}  ->  {size / 100_000_000:.2f} 秒")

    shutil.rmtree(WORK)


if __name__ == "__main__":
    main()
