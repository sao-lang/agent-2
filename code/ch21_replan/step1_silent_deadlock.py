"""第 21 章 · 第 1 级：计划跑到一半失败，会发生什么？

运行：
    python code/ch21_replan/step1_silent_deadlock.py

这一级不修任何东西，只让你看清一个**最危险的失败形态**：
  程序没有抛异常，`run()` 也正常返回了，但计划其实只完成了一半。

线上表现：任务一直显示「处理中」，日志里什么都没有。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    id: str
    goal: str
    action: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"      # pending / done / failed
    result: str = ""
    error: str = ""


TOOLS = {
    "search": lambda args: f"查到 {args.get('q', '?')} 的价格",
    # 注意：没有 search_B —— 这是我们要复现的故障
}


def ready(steps: list[Step]) -> list[Step]:
    done = {s.id for s in steps if s.status == "done"}
    return [s for s in steps if s.status == "pending" and all(d in done for d in s.depends_on)]


def run(steps: list[Step]) -> list[Step]:
    while True:
        batch = ready(steps)
        if not batch:
            return steps                  # ← 注意：这里"正常返回"了
        for s in batch:
            fn = TOOLS.get(s.action)
            if fn is None:
                s.status = "failed"
                s.error = f"未知动作：{s.action}"
            else:
                s.result = fn({})
                s.status = "done"


def main() -> None:
    steps = [
        Step("s1", "查竞品A", "search", []),
        Step("s2", "查竞品B", "search_B", []),          # ← 工具名写错（模型常见错误）
        Step("s3", "对比", "search", ["s1", "s2"]),
        Step("s4", "给建议", "search", ["s3"]),
    ]

    print("=" * 70)
    print("第 1 级：一个步骤失败，整个计划会怎样")
    print("=" * 70)

    result = run(steps)
    for s in result:
        mark = {"done": "✔", "failed": "✘", "pending": "·"}[s.status]
        detail = s.result or s.error or "（从未执行）"
        print(f"  {mark} [{s.id}] {s.goal:<10} {detail}")

    done = sum(1 for s in result if s.status == "done")
    print(f"\n  完成 {done}/{len(result)} 步")
    print(f"  「计划完成」了吗？→ {done == len(result)}")
    print()

    print("=" * 70)
    print("这里发生了什么")
    print("=" * 70)
    print("  ① s2 失败了（工具名写错）")
    print("  ② s3 依赖 s2，所以永远不 ready")
    print("  ③ s4 依赖 s3，同样永远不 ready")
    print("  ④ ready() 返回空 → while 循环退出 → run() **正常返回**")
    print()
    print("  ⚠️ 最危险的是第 ④ 步：没有异常、没有超时、没有任何一条错误日志。")
    print("     如果你只看「run() 有没有抛异常」，你会以为一切正常。")
    print()
    print("  👉 下一级：把「失败」变成一个有类型的信号，然后分级处理。")


if __name__ == "__main__":
    main()
