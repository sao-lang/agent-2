"""第 36 章 step3：并行化 —— 三个互不依赖的检索（离线）。

运行：
    python code/ch36_latency/step3_parallel.py

上一级的痛点：瀑布图显示检索链路 880ms 全在 TTFT 里。
这一级做什么：把其中"互不依赖"的三路并行起来，量出真实收益和它的上限。

并行化的收益有理论上限：
    串行 = a + b + c
    并行 = max(a, b, c)
所以收益取决于"最慢那一路"有多慢。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

# 三路检索，互不依赖（第 31 章的混合检索就是这个结构）
TASKS = [
    ("向量检索", 240),
    ("BM25 检索", 80),
    ("元数据过滤", 60),
]

# 一个真实的坑：如果其中一路依赖另一路的结果，就不能并行
DEPENDENT_TASKS = [
    ("向量检索", 240),
    ("用向量结果做重排", 180),
    ("生成", 640),
]


def run_serial(tasks: list[tuple[str, int]]) -> float:
    t0 = time.perf_counter()
    for _name, ms in tasks:
        time.sleep(ms / 1000)
    return (time.perf_counter() - t0) * 1000


def run_parallel(tasks: list[tuple[str, int]]) -> float:
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        # 每个任务自己 sleep，模拟一次 IO 等待
        list(ex.map(lambda t: time.sleep(t[1] / 1000), tasks))
    return (time.perf_counter() - t0) * 1000


def main() -> None:
    print("=" * 70)
    print("① 三路互不依赖的检索")
    print("=" * 70)
    for name, ms in TASKS:
        print(f"    {name:<14}{ms:>5}ms")
    print()

    serial = run_serial(TASKS)
    parallel = run_parallel(TASKS)
    ceiling = max(ms for _, ms in TASKS)

    print(f"  串行：{serial:>7.0f}ms")
    print(f"  并行：{parallel:>7.0f}ms")
    print(f"  提速：{serial / parallel:.2f}x")
    print()
    print(f"  理论上限 = max(单项) = {ceiling}ms")
    print(f"  实际 {parallel:.0f}ms，比上限多 {parallel - ceiling:.0f}ms —— 这部分是调度开销。")
    print()
    print("  → 关键：**收益取决于最慢那一路**。")
    print("     如果三路是 240/80/60，并行后仍是 240，只省了 140ms。")
    print("     想让 TTFT 再降，就得让最慢那一路变快（换索引、加缓存）。")

    print("\n" + "=" * 70)
    print("② 有依赖的任务不能并行")
    print("=" * 70)
    for name, ms in DEPENDENT_TASKS:
        print(f"    {name:<18}{ms:>5}ms  （依赖上一步）")
    dep_serial = run_serial(DEPENDENT_TASKS)
    print(f"\n  串行：{dep_serial:.0f}ms")
    print("  并行：**不行** —— 后一步的输入来自前一步的输出。")
    print()
    print("  但还有一个办法：**流水线**（下一级）——")
    print("  不是让它们同时开始，而是让『生成』能在『检索』还没全部完成时就开工。")

    print("\n" + "=" * 70)
    print("③ 并行化的三个真实代价")
    print("=" * 70)
    print("  代价 1：错误处理变复杂")
    print("     串行时，第 2 步失败就停；并行的三路里有一路失败怎么办？")
    print("     → 常见做法：`return_exceptions=True`，用可用的那几路继续（降级而非失败）")
    print()
    print("  代价 2：资源峰值变高")
    print("     三路同时打，瞬时并发是原来的 3 倍。")
    print("     → 如果下游是同一个数据库/同一个向量库，并行可能让它更慢。")
    print()
    print("  代价 3：调试变难")
    print("     串行的日志是线性的；并行之后，日志会交错。")
    print("     → 必须用第 39 章的 trace：每个 span 带 parent_id，才看得出谁是谁的子任务。")

    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)
    print(f"  并行化把 {serial:.0f}ms 降到 {parallel:.0f}ms（{serial / parallel:.1f}x），")
    print("  代价是错误处理、资源峰值、可观测性三件事都要补。")
    print()
    print("  而且它只解决了『三路检索』这一段 —— 对整个 TTFT（1522ms）来说，")
    print(f"  收益大约是 {serial - parallel:.0f}ms，约占 {(serial - parallel) / 1522:.0%}。")
    print("  想再进一步，得换另一个手法：流水线（step4）。")


if __name__ == "__main__":
    main()
