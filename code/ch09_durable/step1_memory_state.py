"""第 9 章 · 第 1 级：最容易写出来的"续跑" —— 存在内存里。

运行：
    python code/ch09_durable/step1_memory_state.py

这一级要让你看清一件事：
  **在内存里"恢复状态"是假的** —— 进程一死，什么都没了。

但它不是白写的：这一级的 State 结构，和第 2、3 级的完全一样。
先把"要存什么"想清楚，再谈"存在哪"。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskState:
    """一次长任务的全部进度。

    四个字段，各自解决一个问题：
      goal      —— 我在干什么（人看）
      plan      —— 有几步、分别是什么
      cursor    —— **执行到第几步了**（唯一的进度真相）
      findings  —— 已经产出了什么（续跑时要给模型看的上下文）
    """

    goal: str
    plan: list[str] = field(default_factory=list)
    cursor: int = 0
    findings: list[str] = field(default_factory=list)


class InMemoryRunner:
    """最简单的执行器：状态存在对象里。进程活着才能续跑。"""

    def __init__(self, state: TaskState) -> None:
        self.state = state

    def plan(self) -> None:
        self.state.plan = [f"检索：{self.state.goal}", "整理要点", "撰写结论"]

    def step(self) -> bool:
        """跑一步。返回 False 表示跑完了。"""
        if self.state.cursor >= len(self.state.plan):
            return False
        step = self.state.plan[self.state.cursor]
        self.state.findings.append(f"[完成] {step}")
        self.state.cursor += 1
        return True


def main() -> None:
    print("=" * 68)
    print("第 1 级：状态存在内存里")
    print("=" * 68)

    runner = InMemoryRunner(TaskState(goal="调研竞品定价"))
    runner.plan()

    # 跑两步，模拟"进程跑到一半"
    for _ in range(2):
        runner.step()
    print(f"\n  跑到一半：cursor={runner.state.cursor} findings={runner.state.findings}")

    # 假装进程重启 —— 就是把这个对象丢掉
    del runner
    print("\n  模拟进程重启（del runner）...")

    print("\n" + "=" * 68)
    print("重启之后还剩什么")
    print("=" * 68)
    try:
        print(runner.state)
    except NameError:
        print("  NameError: name 'runner' is not defined")
        print("  → 进度、计划、已经查到的资料，全部消失。")

    print()
    print("  ⚠️ 注意：这不是「写错了」，这是「内存本来就是这么工作的」。")
    print("     很多 demo 用 `app.invoke(...)` 两次来演示「能恢复」，")
    print("     其实两次都在同一个进程里，内存根本没释放过 —— 那证明不了任何事。")
    print()
    print("  👉 下一级：把这份状态写成 JSON 存到磁盘。")
    print("     注意：**要存的字段，和这一级完全一样。** 变的是「存在哪」。")


if __name__ == "__main__":
    main()
