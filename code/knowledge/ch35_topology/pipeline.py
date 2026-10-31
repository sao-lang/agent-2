"""手写流水线：阶段固定、顺序固定，上一阶段的输出就是下一阶段的全部输入。

不联网。每个阶段是一个函数，函数之间靠一份字段契约连接；
示例最后跑一个丢掉字段的坏阶段，看契约在哪里拦住它。

运行：python code/knowledge/ch35_topology/pipeline.py
"""

from __future__ import annotations

from actors import (
    EVIDENCE,
    FINDINGS,
    LOGS,
    SYSTEM,
    Actor,
    World,
    pad,
    print_spans,
)


class ContractError(Exception):
    pass


def check(payload: dict, required: set[str], stage: str) -> None:
    missing = required - set(payload)
    if missing:
        raise ContractError(f"{stage} 的输出缺字段 {sorted(missing)}")


def run() -> tuple[World, dict]:
    world = World()
    reader = Actor("reader", world)
    finder = Actor("finder", world)
    writer = Actor("writer", world)

    merged = "\n".join(LOGS.values())
    reader.run(f"{'x' * SYSTEM}\n# 阶段：合并日志\n{merged}", "合并日志", merged[:40])
    world.handoffs += 1
    world.now_ms += 200

    findings = [FINDINGS[i] for i in (1, 2, 3)]
    evidence = [EVIDENCE[i] for i in (1, 2, 3)]
    finder.run(
        f"{'x' * SYSTEM}\n# 阶段：找错误\n{merged}",
        "找错误",
        "；".join(findings),
        parent=reader.last_span_id,
    )
    world.handoffs += 1
    world.now_ms += 200

    payload = {"findings": findings, "evidence": evidence}
    check(payload, {"findings", "evidence"}, "finder")
    report = "初报：" + "；".join(
        f"{f}（{e}）" for f, e in zip(payload["findings"], payload["evidence"])
    )
    writer.run(
        f"{'x' * SYSTEM}\n# 阶段：写报告\n{payload}",
        "写报告",
        report,
        parent=finder.last_span_id,
    )
    return world, {"report": report, **payload}


def bad_stage() -> None:
    """坏阶段：只交结论，不交依据。下一阶段能明确说出缺什么。"""
    payload = {"findings": ["连接池耗尽"]}
    try:
        check(payload, {"findings", "evidence"}, "finder")
    except ContractError as e:
        print(f"  拦住：{e}")
        print("  <- 阶段契约把'少一个字段'变成一次显式失败，而不是下游的静默猜测")


def main() -> None:
    world, out = run()
    print("=== 1. 流水线的三个阶段 ===")
    print_spans(world)
    print()
    print("=== 2. 阶段之间传的是什么 ===")
    print(f"  reader -> finder：合并后的日志 {sum(len(x) for x in LOGS.values())} 字符")
    print(f"  finder -> writer：findings {len(out['findings'])} 条 + evidence {len(out['evidence'])} 条")
    print(f"  最终报告：{out['report']}")
    print()
    print("=== 3. 一个丢字段的坏阶段 ===")
    bad_stage()
    print()
    print("=== 4. 成本 ===")
    print(f"  agent 数={len({s.agent for s in world.spans})} "
          f"模型调用={world.calls} 消息={world.handoffs} "
          f"token 估={world.tokens} 耗时={world.now_ms}ms")
    print(f"  {pad('串行下界', 12)}三个阶段的耗时相加，没有并行空间")


if __name__ == "__main__":
    main()
