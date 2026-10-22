"""第 26 章 step1：先看"你以为拆完会更好，实际上发生了什么"（离线）。

运行：
    python code/ch26_multi_agent/step1_split_bill.py

上一级的痛点：无（这是起点）。
这一级做什么：把一个**本来能一次做完**的任务拆成 3 个角色，
然后只看三个数字：调用次数、成本、延迟。

之所以能离线跑：用"每次调用固定代价 + 固定耗时"的成本模型，
不调用真模型。你要看的是**结构性倍数**，不是某个模型的单价。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 单次调用的代价（可换成你自己的账单数字），单位：元 / 秒
CALL_COST = 0.006
CALL_LATENCY = 0.30


@dataclass
class Plan:
    name: str
    calls: int
    waves: int          # 串行波数：一波 = 所有可并行的调用同时发出
    context_multiplier: float


PLANS = [
    Plan("单 Agent（一轮做完）", calls=1, waves=1, context_multiplier=1.0),
    Plan("单 Agent + 3 步 ReAct", calls=4, waves=4, context_multiplier=1.0),
    Plan("3 个角色串行分工", calls=4, waves=4, context_multiplier=1.0),
    Plan("3 个角色 + 1 个协调者", calls=7, waves=4, context_multiplier=1.0),
    Plan("3 个角色并行 + 1 次汇总", calls=4, waves=2, context_multiplier=1.0),
]


def main() -> None:
    print("=" * 78)
    print("同一个任务，五种做法：你多花的钱买到了什么")
    print("=" * 78)
    print(f"假设：每次调用 {CALL_COST:.3f} 元 / {CALL_LATENCY * 1000:.0f}ms（串行等待）\n")

    print(f"{'方案':<26}{'调用':>5}{'波数':>5}{'成本(元)':>10}{'延迟(ms)':>10}{'相对成本':>9}")
    print("-" * 78)
    base = PLANS[0]
    for p in PLANS:
        cost = p.calls * CALL_COST
        latency = p.waves * CALL_LATENCY * 1000
        print(f"{p.name:<26}{p.calls:>5}{p.waves:>5}{cost:>10.3f}{latency:>10.0f}"
              f"{cost / (base.calls * CALL_COST):>8.1f}x")

    print("\n" + "=" * 78)
    print("三个能立刻看出来的结论")
    print("=" * 78)
    print("  1. '拆成角色'不会让调用次数变少，只会变多——每个角色都要重读一遍背景。")
    print("  2. 串行分工的延迟是**相加**的；只有并行才可能变短（取 max 而不是 sum）。")
    print("  3. 成本永远只增不减：多 Agent 是成本放大器，不是能力放大器。")

    print("\n" + "=" * 78)
    print("用一个真实的计时验证'并行到底省多少'")
    print("=" * 78)

    def work(ms: int) -> None:
        time.sleep(ms / 1000)

    tasks = [120, 120, 120]
    t0 = time.perf_counter()
    for ms in tasks:
        work(ms)
    serial_ms = (time.perf_counter() - t0) * 1000

    from concurrent.futures import ThreadPoolExecutor

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        list(pool.map(work, tasks))
    parallel_ms = (time.perf_counter() - t0) * 1000

    print("  三个 120ms 的子任务：")
    print(f"    串行：{serial_ms:6.0f}ms")
    print(f"    并行：{parallel_ms:6.0f}ms")
    print(f"    加速：{serial_ms / max(parallel_ms, 1):.2f}x（理论上限 3.00x）")
    print("\n  👉 并行省的是**墙钟时间**，不省调用次数，也不省钱。")
    print("     所以'要不要拆'的真正问题是：你缺的是时间，还是质量？")

    print("\n" + "=" * 78)
    print("下一级：既然拆了更贵，那什么时候**必须**拆？")
    print("=" * 78)
    print("  三个判据：能并行 / 需要互相看 / 单个上下文装不下。")
    print("  缺一个都不该拆——下一级用六个真实任务把这套判据跑一遍。")


if __name__ == "__main__":
    main()
