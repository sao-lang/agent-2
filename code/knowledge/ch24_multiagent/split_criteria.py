"""拆分判据：什么时候该把一个任务交给子 agent。

不联网。判据不是"任务复杂"，而是四条可以逐条回答的问题：
  1 子任务是否需要看不到主上下文（上下文隔离）
  2 子任务之间是否可并行
  3 是否需要独立的裁判或权限边界
  4 交接成本是否小于省下的上下文
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Task:
    name: str
    needs_isolation: bool     # 做这件事时不该看到主上下文
    parallelizable: bool      # 与其他子任务互不依赖
    needs_own_judge: bool     # 需要独立评判或不同权限
    handoff_chars: int        # 交接摘要的字符数
    saved_chars_per_turn: int # 隔离之后每轮省下的字符数


TASKS = [
    Task("读 20 个文件做汇总", True, True, False, 900, 16000),
    Task("跑一遍测试并整理失败", True, False, False, 400, 6000),
    Task("给这次改动写一段说明", False, False, False, 300, 200),
    Task("审查自己的 diff", False, False, True, 500, 0),
    Task("同时调研 3 个方案", True, True, False, 800, 3000),
    Task("把长文档切成条目", False, True, False, 600, 500),
    Task("按仓库规范改一个函数", False, False, False, 200, 100),
    Task("用另一个模型复核答案", False, False, True, 400, 0),
]


def decide(t: Task) -> tuple[str, str]:
    """返回 (结论, 理由)。四条里满足任意两条就值得拆。"""
    hits = []
    if t.needs_isolation:
        hits.append("上下文隔离")
    if t.parallelizable:
        hits.append("可并行")
    if t.needs_own_judge:
        hits.append("独立裁判或权限")
    economic = t.saved_chars_per_turn > t.handoff_chars
    if economic:
        hits.append("省下的上下文大于交接成本")
    if t.needs_own_judge:
        return "拆", "、".join(hits) + "（裁判不能是被审的那个）"
    if len(hits) >= 2:
        return "拆", "、".join(hits)
    if len(hits) == 1 and t.saved_chars_per_turn > t.handoff_chars * 5:
        return "拆", "、".join(hits) + "（收益远大于交接）"
    return "不拆", "、".join(hits) if hits else "四条都不满足"


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 八个任务，按四条判据过一遍 ===")
    print("  " + pad("任务", 30) + pad("隔离", 6) + pad("并行", 6) + pad("裁判", 6) + "结论")
    for t in TASKS:
        verdict, _ = decide(t)
        print("  " + pad(t.name, 30) + pad("是" if t.needs_isolation else "否", 6)
              + pad("是" if t.parallelizable else "否", 6)
              + pad("是" if t.needs_own_judge else "否", 6) + verdict)

    print()
    print("=== 2. 每个结论的理由 ===")
    for t in TASKS:
        verdict, why = decide(t)
        print(f"  {pad(t.name, 30)}{verdict}  <- {why}")

    print()
    print("=== 3. 只看'任务复杂'会怎么判 ===")
    for t in TASKS:
        verdict, _ = decide(t)
        complex_guess = t.saved_chars_per_turn > 1000 or t.parallelizable
        flag = "一致" if (verdict == "拆") == complex_guess else "不一致"
        if flag == "不一致":
            print(f"  {pad(t.name, 30)}按复杂度会{'拆' if complex_guess else '不拆'}，"
                  f"按判据应当{verdict}")
    print("  <- 复杂度是结果，不是判据；判据是上下文隔离与交接成本")


if __name__ == "__main__":
    main()
