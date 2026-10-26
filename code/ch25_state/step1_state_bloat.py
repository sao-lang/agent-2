"""第 24 章 step1：State 里多放一个字段，会发生什么（离线）。

运行：
    python code/ch25_state/step1_state_bloat.py

上一级的痛点：第 23 章证明了"状态要落盘"，但没回答"**到底该存什么**"。

这一级做什么：同一个任务，用三种 State 定义跑一遍，只比三个数字：
  · 单个检查点多大（磁盘 / 传输）
  · 总量多大
  · 能不能看出"现在进行到哪"

三种定义：
  A 只存进度（goal + cursor + 计划）
  B 进度 + 全部中间产出（每步的原文都塞进去）
  C 进度 + 产出摘要 + 引用（只存 id 和摘要）

结论：**State 不是"越多越好"，是"够恢复就好"。**
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 模拟一次 6 步的任务：每一步产出一大段（比如一份 2,000 字的检索结果）
STEPS = ["检索政策", "检索竞品 A", "检索竞品 B", "整理要点", "交叉核对", "撰写结论"]
STEP_OUTPUT_CHARS = 2000


def fake_output(i: int) -> str:
    return f"[{STEPS[i]}] " + ("资料内容" * (STEP_OUTPUT_CHARS // 4))


def fake_summary(i: int) -> str:
    return f"{STEPS[i]}：命中 3 条，关键点「要点{i + 1}」"


@dataclass
class StateA:
    goal: str
    plan: list[str] = field(default_factory=list)
    cursor: int = 0


@dataclass
class StateB:
    goal: str
    plan: list[str] = field(default_factory=list)
    cursor: int = 0
    outputs: list[str] = field(default_factory=list)        # ← 全部原文


@dataclass
class StateC:
    goal: str
    plan: list[str] = field(default_factory=list)
    cursor: int = 0
    summaries: list[str] = field(default_factory=list)      # ← 摘要
    artifact_ids: list[str] = field(default_factory=list)   # ← 原文存外部，只留引用


def size_of(obj) -> int:
    return len(json.dumps(asdict(obj), ensure_ascii=False).encode("utf-8"))


def run(state, n_steps: int) -> list[int]:
    """跑 n 步，返回每个检查点的大小（字节）。"""
    sizes = []
    for i in range(n_steps):
        if isinstance(state, StateB):
            state.outputs.append(fake_output(i))
        elif isinstance(state, StateC):
            state.summaries.append(fake_summary(i))
            state.artifact_ids.append(f"art-{i:03d}")
        state.cursor = i + 1
        sizes.append(size_of(state))
    return sizes


def main() -> None:
    plan = list(STEPS)
    print("=" * 76)
    print("同一个 6 步任务，三种 State 定义")
    print("=" * 76)
    print(f"每步原始产出约 {STEP_OUTPUT_CHARS} 字符；6 步累计约 {STEP_OUTPUT_CHARS * 6:,} 字符\n")

    results = {}
    for name, state in (
        ("A 只存进度", StateA(goal="调研竞品定价", plan=plan)),
        ("B 存全部原文", StateB(goal="调研竞品定价", plan=plan)),
        ("C 摘要 + 引用", StateC(goal="调研竞品定价", plan=plan)),
    ):
        sizes = run(state, len(plan))
        results[name] = sizes
        print(f"  [{name}] 各步检查点大小（字节）：{sizes}")

    print("\n" + "=" * 76)
    print("三个数字")
    print("=" * 76)
    print(f"  {'定义':<14}{'末步检查点':>12}{'总量':>10}{'相对 A':>9}")
    print("  " + "-" * 47)
    base = sum(results["A 只存进度"])
    for name, sizes in results.items():
        total = sum(sizes)
        print(f"  {name:<14}{sizes[-1]:>12,}{total:>10,}{total / base:>8.1f}x")

    print("\n" + "=" * 76)
    print("结论：State 的设计标准是'够恢复就好'")
    print("=" * 76)
    print("  · A 太小：恢复时不知道前面产出了什么，模型只能重跑一遍（浪费钱）")
    print("  · B 太大：每个检查点都带着全部原文，写盘/传输/回放都变慢，")
    print("           而且这些东西**本来就有别的地方存**（文件、数据库、向量库）")
    print("  · C 刚好：摘要让模型知道'前面做了什么'，引用让需要原文时能取回")
    print()
    print("  所以 State 里应该放的是：**决策所需的最小信息**。")
    print("  不是'所有发生过的事'，而是'继续做下去需要知道的事'。")

    print("\n" + "=" * 76)
    print("下一级：那'最小信息'具体是哪几类？给它们分类")
    print("=" * 76)
    print("  下一级会把 State 的字段按**生命周期**分成四类：")
    print("    目标 / 进度 / 事实 / 引用 —— 每一类的清理策略都不同。")


if __name__ == "__main__":
    main()
