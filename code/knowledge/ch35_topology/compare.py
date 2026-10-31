"""同一任务跑四种手写拓扑：控制权、消息数、上下文与耗时的对照。

不联网。四个 run() 都用 ch35_topology/actors.py 里的脚本化 actor。
每个数都来自脚本，正文里的表就是这段输出。

运行：python code/knowledge/ch35_topology/compare.py
"""

from __future__ import annotations

import blackboard
import handoff
import pipeline
import supervisor
from actors import pad


def metric(world, report: str, label: str) -> dict:
    peak = max(s.prompt_chars for s in world.spans)
    return {
        "label": label,
        "agents": len({s.agent for s in world.spans}),
        "calls": world.calls,
        "messages": world.handoffs,
        "tokens": world.tokens,
        "ms": world.now_ms,
        "peak": peak,
        "report": report,
    }


def main() -> None:
    rows = []
    w, r, _ = supervisor.run()
    rows.append(metric(w, r, "supervisor"))
    w, r, _ = handoff.run()
    rows.append(metric(w, r, "handoff"))
    w, r, _ = blackboard.run()
    rows.append(metric(w, r, "blackboard"))
    w, out = pipeline.run()
    rows.append(metric(w, out["report"], "pipeline"))

    print("=== 1. 四种拓扑跑同一任务 ===")
    print("  " + pad("拓扑", 12) + pad("agent", 7) + pad("调用", 6)
          + pad("消息", 6) + pad("token", 8) + pad("耗时ms", 8) + "峰值上下文")
    for m in rows:
        print("  " + pad(m["label"], 12) + pad(str(m["agents"]), 7)
              + pad(str(m["calls"]), 6) + pad(str(m["messages"]), 6)
              + pad(str(m["tokens"]), 8) + pad(str(m["ms"]), 8) + str(m["peak"]))

    print()
    print("=== 2. 报告是否一致 ===")
    for m in rows:
        print(f"  {pad(m['label'], 12)}{m['report'][:52]}")
    print("  <- 结论相同，但 blackboard 的报告多带了依据；这是拓扑对产物形状的影响")
    print()
    print("=== 3. 相对 supervisor 的调用与消息 ===")
    base = rows[0]
    for m in rows[1:]:
        print(f"  {pad(m['label'], 12)}调用 {m['calls'] - base['calls']:+d}，"
              f"消息 {m['messages'] - base['messages']:+d}，"
              f"token {m['tokens'] - base['tokens']:+d}")
    print("  <- handoff 省掉中心节点的调用，代价是没有全局视角；"
          "blackboard 与 supervisor 消息数相同，但少了三次中心决策调用")


if __name__ == "__main__":
    main()
