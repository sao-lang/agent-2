"""扇出并行的加速比：四条互不依赖的支路，串行跑 vs 并行跑。

不联网。每条支路的"耗时"用 sleep 模拟一次工具调用的往返（原理演示，不是实测网络）。
并行只对"互不依赖"的支路有效；这一点由 DAG 决定，不由线程数决定。

运行：python code/forms/graph_engineering/fanout_speedup.py
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

BRANCHES = ["查订单", "查物流", "查退款政策", "查库存"]
LATENCY = 0.08                 # 每条支路一次调用的往返，秒


def branch(name: str) -> str:
    time.sleep(LATENCY)        # 模拟一次远程调用
    return f"{name}: ok"


def serial() -> tuple[list[str], float]:
    t0 = time.perf_counter()
    out = [branch(b) for b in BRANCHES]
    return out, time.perf_counter() - t0


def parallel(workers: int = 4) -> tuple[list[str], float]:
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        out = list(pool.map(branch, BRANCHES))
    return out, time.perf_counter() - t0


def main() -> None:
    print("=== 1. 同一组四条支路，两种跑法 ===")
    _, t_serial = serial()
    _, t_parallel = parallel()
    print(f"    串行：{t_serial * 1000:7.1f} ms   （{len(BRANCHES)} 次 {LATENCY * 1000:.0f} ms 相加）")
    print(f"    并行：{t_parallel * 1000:7.1f} ms   （4 个线程同时等）")
    print(f"    加速比：{t_serial / t_parallel:.2f}x")

    print()
    print("=== 2. 加两条不并行的支路会怎样 ===")
    t0 = time.perf_counter()
    a = branch("汇总")
    b = branch(f"基于汇总再查一次：{a}")
    t_chain = time.perf_counter() - t0
    print(f"    两条有依赖的支路串起来：{t_chain * 1000:7.1f} ms "
          f"（并行化之后仍是 {LATENCY * 2000:.0f} ms 的量级）")

    print()
    print("=== 3. 线程数超过支路数没有收益 ===")
    for workers in (1, 2, 4, 8):
        _, t = parallel(workers)
        print(f"    workers={workers}: {t * 1000:7.1f} ms")

    print()
    print("=== 4. 并行只在'状态能分开写'时成立 ===")
    print("    四条支路各写自己的字段 -> 无冲突")
    print("    四条支路都写同一个 findings 列表 -> 需要 append reducer 或有唯一 owner")
    print("    否则最后写赢，前三个的发现直接消失（第 48 章 5.2）")


if __name__ == "__main__":
    main()
