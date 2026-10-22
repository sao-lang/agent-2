"""第 23 章 step2：State 的字段按"生命周期"分四类（离线）。

运行：
    python code/ch23_state/step2_field_lifecycle.py

上一级的痛点：知道"要放最小信息"，但不知道"每样信息该活多久"。

这一级做什么：把 State 的所有字段按生命周期分成四类，然后模拟一次 8 步任务，
看每一类字段随着任务推进**变大还是不变**——这决定了它该不该被裁剪。

四类：
  goal     目标      整个任务不变          永远不清
  progress 进度      每步 +1               永远不清（这是续跑的唯一真相）
  facts    事实      会累积、会过期        要裁剪（只留最近 + 关键的）
  refs     引用      只增不减              不清，但**不放进 prompt**
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass
class State:
    goal: str                                   # ① 目标
    plan: list[str] = field(default_factory=list)
    cursor: int = 0                             # ② 进度
    facts: list[str] = field(default_factory=list)      # ③ 事实（会膨胀）
    refs: list[str] = field(default_factory=list)       # ④ 引用（原文在外部）
    errors: list[str] = field(default_factory=list)     # ③' 例外：错误也要留证据


STEPS = ["检索", "阅读", "提取", "核对", "补充", "写作", "自查", "定稿"]


def step(state: State, i: int) -> None:
    state.facts.append(f"[{STEPS[i]}] 事实{i + 1}：竞品{i % 3 + 1} 定价 {99 + i} 元")
    state.refs.append(f"doc-{i:03d}#p{10 + i}")
    if i == 5:
        state.errors.append("核对时发现竞品 A 的两个来源冲突（99 vs 109）")
    state.cursor = i + 1


def prompt_view(state: State, max_facts: int) -> str:
    """真正喂给模型的视图：goal + 进度 + 最近的事实 + 错误（引用不进来）。"""
    recent = state.facts[-max_facts:]
    parts = [
        f"目标：{state.goal}",
        f"进度：{state.cursor}/{len(state.plan)} —— 当前步骤：{state.plan[state.cursor] if state.cursor < len(state.plan) else '已完成'}",
        "最近的事实：\n" + "\n".join(f"  - {f}" for f in recent),
    ]
    if state.errors:
        parts.append("已知问题：\n" + "\n".join(f"  - {e}" for e in state.errors))
    return "\n".join(parts)


def main() -> None:
    s = State(goal="写一份竞品定价对比", plan=list(STEPS))

    print("=" * 78)
    print("四类字段随任务推进的变化")
    print("=" * 78)
    print(f"{'步':>3}{'goal':>7}{'cursor':>8}{'facts':>7}{'refs':>6}{'errors':>8}{'喂给模型的字符':>14}")
    print("-" * 78)
    for i, name in enumerate(STEPS):
        step(s, i)
        view = prompt_view(s, max_facts=3)
        print(f"{name:>3}{1:>7}{s.cursor:>8}{len(s.facts):>7}{len(s.refs):>6}{len(s.errors):>8}{len(view):>14}")

    print("-" * 78)
    print(f"  最终 State 里的条目数：facts={len(s.facts)} refs={len(s.refs)} errors={len(s.errors)}")
    print(f"  但喂给模型的只有 {len(prompt_view(s, 3))} 字符（最近 3 条事实 + 错误）")

    print("\n" + "=" * 78)
    print("四类的规则")
    print("=" * 78)
    rules = [
        ("goal", "目标", "整个任务不变", "永远不清；它就是'我在干什么'"),
        ("cursor", "进度", "每步 +1", "永远不清；续跑的唯一真相"),
        ("facts", "事实", "累积、会过期", "**要裁剪**：只留最近 N 条 + 被标记为关键的那些"),
        ("errors", "问题", "只增不减，但很少", "不清；这些是'为什么最后答案是保守的'依据"),
        ("refs", "引用", "只增不减", "不清，但**不放进 prompt**；需要原文时按 id 取回"),
    ]
    print(f"  {'字段':<10}{'类别':<8}{'变化':<14}{'策略'}")
    print("  " + "-" * 70)
    for f, k, ch, policy in rules:
        print(f"  {f:<10}{k:<8}{ch:<14}{policy}")

    print("\n" + "=" * 78)
    print("为什么 refs 不该放进 prompt")
    print("=" * 78)
    print("  模型不需要知道'我引用过 doc-000#p10'，它需要的是**内容**。")
    print("  引用是给人（和审计）看的，不是给模型看的。")
    print("  → 放进 prompt 只会白烧 token，还会挤掉真正有用的东西（第 24 章）。")

    print("\n" + "=" * 78)
    print("为什么 errors 不能裁掉")
    print("=" * 78)
    print("  '竞品 A 的两个来源冲突'这条如果被裁掉，最后写出来的报告会")
    print("  挑一个数字当定论——而实际上它是不确定的。")
    print("  → 例外和冲突要**永远**留在 State 里，直到人明确解决它。")

    print("\n" + "=" * 78)
    print("下一级：字段定好了，怎么防止它们被并发写坏")
    print("=" * 78)
    print("  LangGraph 里多个分支同时写一个字段 → 需要 reducer；")
    print("  裸 asyncio 里两个协程同时改一个 dict → 需要锁或串行化。")
    print("  下一级会演示这两种'静默丢数据'。")


if __name__ == "__main__":
    main()
