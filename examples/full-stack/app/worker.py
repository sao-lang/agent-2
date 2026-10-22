"""独立 worker 进程：真实部署里它和 agent-api 是两个容器、两份副本。

为什么长任务一定要独立进程？
  · API 要"快速返回"，长任务会占满 event loop / 线程池
  · 扩缩容粒度不同：API 看 QPS，worker 看队列积压
  · 崩溃隔离：worker 被一个大任务搞 OOM，不该带走 API
"""
from __future__ import annotations

import os
import signal
import time

STOP = False


def _handle(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"[worker] 收到 {signal.Signals(signum).name}，处理完当前任务后退出", flush=True)


def main() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle)
        except ValueError:
            pass

    redis_url = os.getenv("REDIS_URL", "not configured")
    print(f"[worker] 启动，队列后端 = {redis_url}", flush=True)
    n = 0
    while not STOP:
        # 真实实现：BRPOP queue 或 XREADGROUP，这里用 sleep 代替
        time.sleep(0.5)
        n += 1
        # 心跳文件：容器没有 HTTP 端口时，健康检查只能靠外部可见的信号
        with open("/tmp/worker.heartbeat", "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        if n % 10 == 0:
            print(f"[worker] 心跳 #{n}（已处理 0 个真实任务，这是占位实现）", flush=True)
    print(f"[worker] 退出，本次共 {n} 个心跳周期", flush=True)


if __name__ == "__main__":
    main()
