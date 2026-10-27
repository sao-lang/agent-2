"""一个 4 步 DAG：串行执行 vs 按依赖并发执行。

不联网。工具用 sleep 模拟耗时，用来对比墙钟时间。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor


def tool(name: str, cost: float) -> str:
    time.sleep(cost)
    return name


# 依赖表：每步依赖哪些前序步骤
DAG = {
    "order": [],            # 不需要前置
    "user": [],             # 不需要前置
    "logistics": ["order"], # 需要订单号
    "policy": [],           # 不需要前置
}

COST = {"order": 0.30, "user": 0.20, "logistics": 0.25, "policy": 0.15}


def serial(dag: dict[str, list[str]]) -> tuple[dict[str, str], float]:
    t0 = time.perf_counter()
    done: dict[str, str] = {}
    for name in dag:                       # 按书写顺序，不考虑依赖
        done[name] = tool(name, COST[name])
    return done, time.perf_counter() - t0


def layered(dag: dict[str, list[str]]) -> tuple[list[list[str]], float]:
    """按依赖分层，同层并发。"""
    remaining = dict(dag)
    layers: list[list[str]] = []
    done: dict[str, str] = {}
    t0 = time.perf_counter()
    while remaining:
        ready = [n for n, deps in remaining.items() if all(d in done for d in deps)]
        if not ready:
            raise RuntimeError(f"依赖成环：{list(remaining)}")
        layers.append(ready)
        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            for name, result in zip(ready, pool.map(lambda n: tool(n, COST[n]), ready)):
                done[name] = result
        for n in ready:
            del remaining[n]
    return layers, time.perf_counter() - t0


def main() -> None:
    _, t_serial = serial(DAG)
    layers, t_layered = layered(DAG)

    print(f"串行：{t_serial:.2f}s")
    for name in DAG:
        print(f"  {name:<10}{COST[name]:.2f}s")
    print()
    print(f"并发：{t_layered:.2f}s")
    for i, layer in enumerate(layers, 1):
        costs = [COST[n] for n in layer]
        print(f"  层 {i}: {layer}  最大耗时 {max(costs):.2f}s")
    print()
    print(f"加速比：{t_serial / t_layered:.2f}x")
    print("注：串行总耗时等于各步之和，并发总耗时等于各层最大值之和。")


if __name__ == "__main__":
    main()
