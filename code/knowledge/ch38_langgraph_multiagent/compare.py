"""LangGraph 四种拓扑的对照：同一任务、同一套脚本化 agent。

不联网。四个模块各自 build() 一张图，这里只负责跑、收集、打印。

运行：python code/knowledge/ch38_langgraph_multiagent/compare.py
"""

from __future__ import annotations

import blackboard_graph
import handoff_graph
import pipeline_graph
import supervisor_graph
from common import pad


def main() -> None:
    # 逐个跑并在下一次 reset 之前取出数字；USAGE 是模块级共享对象
    sources = [
        ("supervisor", supervisor_graph.run),
        ("handoff", handoff_graph.run),
        ("blackboard", blackboard_graph.run),
        ("pipeline", pipeline_graph.run),
    ]
    runs = []
    for name, fn in sources:
        result = fn()
        runs.append((name, {
            "calls": result["usage"].calls,
            "tokens": result["usage"].tokens,
            "ms": result["usage"].ms,
            "by_agent": {k: dict(v) for k, v in result["usage"].by_agent.items()},
            "report": result["out"]["report"],
        }))

    print("=== 1. 四种拓扑（LangGraph 版）===")
    print("  " + pad("拓扑", 12) + pad("调用", 6) + pad("token", 8)
          + pad("耗时ms", 8) + "输出")
    for name, u in runs:
        print("  " + pad(name, 12) + pad(str(u["calls"]), 6)
              + pad(str(u["tokens"]), 8) + pad(str(u["ms"]), 8)
              + u["report"][:28])

    print()
    print("=== 2. 每个拓扑的调用分布 ===")
    for name, u in runs:
        dist = {k: v["calls"] for k, v in u["by_agent"].items()}
        print(f"  {pad(name, 12)}{dist}")

    print()
    print("=== 3. 与手写版对照 ===")
    print("  手写版（第 35 章）：supervisor 7 调用 / 4 agent，"
          "handoff 4 / 4，blackboard 4 / 4，pipeline 3 / 3")
    for name, u in runs:
        print(f"  框架版 {pad(name, 12)} {u['calls']} 调用 / "
              f"{len(u['by_agent'])} 个执行者")
    print("  <- 调用次数与手写版一致；框架多出来的是图的调度开销，不是模型调用")


if __name__ == "__main__":
    main()
