"""手写 handoff：控制权从一个人交给下一个人，交出去的人不再回来。

不联网，actor 是脚本化替身。与 supervisor 的差别只有一处：
没有中心节点，谁接手谁负责，交出的上下文就是全部上下文。

运行：python code/knowledge/ch35_topology/handoff.py
"""

from __future__ import annotations

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

TASK = "读三份日志，定位错误，写一份事故初报"


def run() -> tuple[World, str, list[Brief]]:
    world = World()
    agents = [Actor(f"agent{i}", world) for i in (1, 2, 3)]
    writer = Actor("writer", world)
    briefs: list[Brief] = []

    context = f"{TASK}\n已知结论：无\n"
    prev: str | None = None
    for i in (1, 2, 3):
        if i > 1:
            world.handoffs += 1
            world.now_ms += 200
        prompt = (
            f"{'x' * SYSTEM}\n"
            f"# 任务\n{TASK}\n"
            f"# 交接上下文\n{context}\n"
            f"# 你这一棒\n读日志 {i}，补一条发现，然后把上下文交给下一棒。\n"
            f"# 日志\n<<<\n{LOGS[i]}\n>>>"
        )
        reply = f"{FINDINGS[i]}（{EVIDENCE[i]}）"
        agents[i - 1].run(prompt, f"第 {i} 棒", reply, parent=prev)
        prev = agents[i - 1].last_span_id
        briefs.append(
            Brief(
                task=f"第 {i} 棒",
                result=FINDINGS[i],
                evidence=EVIDENCE[i],
                usage_tokens=int(len(prompt) * 0.6) + 20,
            )
        )
        context += f"- {reply}\n"

    world.handoffs += 1
    world.now_ms += 200
    report = write_report(writer, briefs, parent=prev)
    return world, report, briefs


def main() -> None:
    world, report, briefs = run()
    print("=== 1. handoff 的调用顺序 ===")
    print_spans(world)
    print()
    print("=== 2. 每一棒接手时看到的上下文 ===")
    for s in world.spans:
        if s.agent.startswith("agent"):
            print(f"  {pad(s.agent, 9)}输入 {s.prompt_chars} 字符，"
                  f"交给下一棒 {s.reply_chars} 字符")
    print("  <- 上下文逐棒变大；最后一棒看到的是前三棒的链，不是三份日志")
    print()
    print("=== 3. 汇总结果 ===")
    print(f"  {report}")
    print(f"  agent 数={len({s.agent for s in world.spans})} "
          f"模型调用={world.calls} 消息={world.handoffs} "
          f"token 估={world.tokens} 耗时={world.now_ms}ms")


if __name__ == "__main__":
    main()
