"""手写 blackboard：worker 把发现贴到共享工作区，写者最后读板。

不联网。示例用一段确定的交错顺序复现"丢更新"：
两个 worker 同时读到同一份空板，各自追加，再把整份板写回；后写的覆盖前一个。

运行：python code/knowledge/ch35_topology/blackboard.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from actors import (
    EVIDENCE,
    FINDINGS,
    LOGS,
    SYSTEM,
    Actor,
    Brief,
    World,
    pad,
    print_spans,
    write_report,
)


@dataclass
class Board:
    findings: list[str] = field(default_factory=list)
    writes: int = 0

    def snapshot(self) -> list[str]:
        return list(self.findings)

    def merge(self, items: list[str]) -> None:
        for item in items:
            if item not in self.findings:
                self.findings.append(item)
        self.writes += 1

    def overwrite(self, snapshot: list[str]) -> None:
        """整份写回：拿的是旧快照，写回时把中间发生的一切盖掉。"""
        self.findings = list(snapshot)
        self.writes += 1


def run() -> tuple[World, str, Board]:
    world = World()
    workers = [Actor(f"worker{i}", world) for i in (1, 2, 3)]
    writer = Actor("writer", world)
    board = Board()
    briefs: list[Brief] = []
    prev: str | None = None

    for i in (1, 2, 3):
        world.handoffs += 1
        world.now_ms += 200
        seen = board.snapshot()
        prompt = (
            f"{'x' * SYSTEM}\n"
            f"# 任务\n读日志 {i} 找错误，把发现追加到板上。\n"
            f"# 板上已有\n{seen}\n"
            f"# 日志\n<<<\n{LOGS[i]}\n>>>"
        )
        workers[i - 1].run(prompt, f"读日志 {i}", FINDINGS[i], parent=prev)
        prev = workers[i - 1].last_span_id
        board.merge([f"{FINDINGS[i]}（{EVIDENCE[i]}）"])
        briefs.append(Brief(task=f"日志 {i}", result=FINDINGS[i], evidence=EVIDENCE[i]))

    world.handoffs += 1
    world.now_ms += 200
    board_text = "\n".join(f"- {x}" for x in board.findings)
    report = writer.run(
        f"{'x' * SYSTEM}\n# 任务\n读板写初报。\n# 板\n{board_text}",
        "读板写报告",
        "初报：" + "；".join(board.findings),
        parent=prev,
    )
    return world, report, board


def conflict() -> None:
    print("=== 2. 同一段交错，两种写回方式 ===")
    print("  步骤：A 读板 -> B 读板 -> A 写回 -> B 写回")
    lost = Board()
    a = lost.snapshot()
    b = lost.snapshot()
    a.append("A 的发现")
    lost.overwrite(a)
    b.append("B 的发现")
    lost.overwrite(b)
    print(f"  整份写回之后：{lost.findings}")
    print(f"  <- A 的发现被 B 的旧快照盖掉，板只涨了 {len(lost.findings)} 条")

    merged = Board()
    a = merged.snapshot()
    b = merged.snapshot()
    a.append("A 的发现")
    merged.merge(a)
    b.append("B 的发现")
    merged.merge(b)
    print(f"  按增量合并之后：{merged.findings}")
    print("  <- 两次写都保留；reducer 写回的是'我新增的部分'，不是'我看到的全部'")


def main() -> None:
    world, report, board = run()
    print("=== 1. blackboard 的调用顺序 ===")
    print_spans(world)
    print()
    print(f"  板上的发现（{len(board.findings)} 条）：")
    for item in board.findings:
        print(f"    - {item}")
    print(f"  汇总：{report}")
    print(f"  agent 数={len({s.agent for s in world.spans})} "
          f"模型调用={world.calls} 消息={world.handoffs} "
          f"token 估={world.tokens} 耗时={world.now_ms}ms")
    print()
    conflict()
    print()
    print("=== 3. 板的所有权 ===")
    print("  字段            写者          冲突处理")
    print("  发现列表        各 worker     增量合并（merge）")
    print("  最终报告        writer        唯一写者")
    print("  预算与用量      每个 actor    原子累加，不做读改写")


if __name__ == "__main__":
    main()
