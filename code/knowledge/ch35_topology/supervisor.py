"""手写 supervisor：中心节点决定下一步派给谁，worker 只交回交接单。

不联网，actor 是脚本化替身。统计 agent 数、消息数、上下文与虚拟耗时。

运行：python code/knowledge/ch35_topology/supervisor.py
"""

from __future__ import annotations

from actors import (
    Actor,
    Brief,
    World,
    pad,
    print_spans,
    read_log,
    write_report,
)

TASK = "读三份日志，定位错误，写一份事故初报"


def run() -> tuple[World, str, list[Brief]]:
    world = World()
    supervisor = Actor("supervisor", world)
    workers = [Actor(f"worker{i}", world) for i in (1, 2, 3)]

    briefs: list[Brief] = []
    for i in (1, 2, 3):
        # 中心节点每派一次活，自己也要花一次调用：看已有结论、决定下一个是谁
        prompt = (
            f"任务：{TASK}\n"
            f"已有结论：{[b.result for b in briefs]}\n"
            f"下一个派给谁？只剩 worker{i}，回 worker{i}"
        )
        supervisor.run(prompt, f"决定派发 {i}", f"worker{i}")
        world.handoffs += 1
        world.now_ms += 200
        briefs.append(read_log(workers[i - 1], i, parent=supervisor.last_span_id))

    world.handoffs += 1
    world.now_ms += 200
    report = write_report(supervisor, briefs, parent=workers[-1].last_span_id)
    return world, report, briefs


def main() -> None:
    world, report, briefs = run()
    print("=== 1. supervisor 的调用顺序 ===")
    print_spans(world)
    print()
    print("=== 2. 交回的交接单 ===")
    for b in briefs:
        print(f"  {pad(b.task, 16)}result={b.result}")
        print(f"  {pad('', 16)}evidence={b.evidence} confidence={b.confidence}")
    print()
    print("=== 3. 汇总结果 ===")
    print(f"  {report}")
    print(f"  agent 数={len({s.agent for s in world.spans})} "
          f"模型调用={world.calls} 消息={world.handoffs} "
          f"token 估={world.tokens} 耗时={world.now_ms}ms")


if __name__ == "__main__":
    main()
