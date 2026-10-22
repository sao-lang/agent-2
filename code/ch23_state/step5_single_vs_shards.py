"""第 23 章 step5：一个大字典 vs 四个小对象（离线）。

运行：
    python code/ch23_state/step5_single_vs_shards.py

上一级的痛点：字段怎么迁移解决了，但还有个更早的问题没回答：
**State 该写成一个包里什么都有的 dict，还是拆成几个各自负责的小对象？**

这一级做什么：用同一份数据，写两种结构，跑同一段"写第 5 步"的代码，
比三个东西：写入方要 import 多少、一次改动波及多少行、测试要 mock 多少。

最后一节给出**拆分的唯一判据**：这个字段会不会被"另一个角色"写？
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ---------------------------------------------------------------- 结构 A：一个大字典

BigState = dict


def big_advance(state: BigState, step_name: str, fact: str) -> None:
    """一段普通得不能再普通的业务代码——但它顺手改了 5 个字段。"""
    state["cursor"] += 1
    state["facts"].append(fact)
    state["refs"].append(f"doc-{state['cursor']:03d}")
    state["history"].append(step_name)
    state["updated_at"] = state["cursor"]


# ---------------------------------------------------------------- 结构 B：四个小对象

@dataclass
class Goal:
    text: str
    plan: list[str] = field(default_factory=list)


@dataclass
class Progress:
    cursor: int = 0
    history: list[str] = field(default_factory=list)


@dataclass
class Facts:
    items: list[str] = field(default_factory=list)


@dataclass
class Refs:
    ids: list[str] = field(default_factory=list)


@dataclass
class ShardedState:
    goal: Goal
    progress: Progress = field(default_factory=Progress)
    facts: Facts = field(default_factory=Facts)
    refs: Refs = field(default_factory=Refs)


def sharded_advance(state: ShardedState, step_name: str, fact: str) -> None:
    """同样的业务动作，但每个对象只碰自己那一块。"""
    state.progress.cursor += 1
    state.progress.history.append(step_name)
    state.facts.items.append(fact)
    state.refs.ids.append(f"doc-{state.progress.cursor:03d}")


def main() -> None:
    print("=" * 78)
    print("同名动作，两种结构")
    print("=" * 78)
    big: BigState = {"goal": "写竞品报告", "plan": [], "cursor": 0,
                     "facts": [], "refs": [], "history": [], "updated_at": 0}
    small = ShardedState(goal=Goal("写竞品报告"))

    for i, name in enumerate(["检索", "提取", "核对", "写作", "定稿"], 1):
        big_advance(big, name, f"事实{i}")
        sharded_advance(small, name, f"事实{i}")

    print(f"  大字典：cursor={big['cursor']} facts={len(big['facts'])} refs={len(big['refs'])}")
    print(f"  分对象：cursor={small.progress.cursor} facts={len(small.facts.items)} refs={len(small.refs.ids)}")
    print("  → 结果一样。差别不在功能，在**以后的维护成本**。")

    print("\n" + "=" * 78)
    print("三个可量的差别")
    print("=" * 78)
    metrics = [
        ("写一个字段要引用几个名字", "state['facts']（一处拼错就 KeyError）", "state.facts.items（拼错立刻 AttributeError）"),
        ("加一个字段，要改哪些地方", "所有造 dict 的地方（测试里也有）", "只改对应 dataclass"),
        ("谁能写这个字段", "任何拿到 dict 的函数", "只有拿到对应对象的函数"),
        ("非法状态能不能构造出来", "能（缺键、类型错、混合语义）", "dataclass 的默认值就不允许"),
        ("序列化", "直接 json", "需要 asdict 或自定义"),
    ]
    print(f"  {'维度':<24}{'大字典':<38}{'分对象'}")
    print("  " + "-" * 92)
    for a, b, c in metrics:
        print(f"  {a:<24}{b:<38}{c}")

    print("\n" + "=" * 78)
    print("但别急着拆：拆错比不拆更痛")
    print("=" * 78)
    print("  常见的拆错方式：按'技术层次'拆")
    print("    ✗ LLMState / ToolState / MemoryState   ← 一次业务动作要横跨三个对象")
    print("  正确的拆法：按'谁会写它'拆")
    print("    ✓ goal（只读）/ progress（执行器写）/ facts（各节点写）/ refs（各节点写）")

    print("\n" + "=" * 78)
    print("唯一判据")
    print("=" * 78)
    print("  **这个字段会不会被'另一个角色'写？**")
    print()
    print("  · 不会 → 留在同一块（同一个节点写的东西，拆开只是多一层 .")
    print("  · 会   → 拆开，并且给它一个明确的写入者（谁负责、什么时候写、怎么合并）")
    print()
    print("  还有一个更硬的信号：**这个字段会不会被并行分支写？**")
    print("  会 → 它必须是一个'可合并'的类型（list + reducer），见 step3。")

    print("\n" + "=" * 78)
    print("本章总结：State 是三个契约")
    print("=" * 78)
    print("  1. **生命周期契约**：goal 不变、cursor 只增、facts 可裁、refs 不进 prompt（step2）")
    print("  2. **并发契约**：会被并行写的字段，必须有合并规则（step3）")
    print("  3. **恢复契约**：带版本号、逐级迁移、只存可序列化的东西（step4）")
    print()
    print("  满足这三条，State 就不会成为那个'出了问题却查不出来'的地方。")


if __name__ == "__main__":
    main()
