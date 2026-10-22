"""第 57 章 step1：一句"AI 不稳定"，能走多远（离线）。

运行：
    python code/ch56_postmortem/step1_vague_root_cause.py

上一级的痛点：无（这是起点）。
这一级做什么：把四个"看起来像根因"的说法，逐条拿去对照证据，看它们能推出什么修复。

对照的判据只有一条：
  **能不能指出"具体哪个 span、看到了什么输入、发生了什么"。**

结论会有点刺眼：四个说法里，三个推不出任何可执行的修复，
剩下那一个能推出来的，恰好也不是"模型的问题"。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class Claim:
    text: str               # 原始说法
    span: str | None        # 指向哪个 span（None = 指不出来）
    evidence: str           # 证据
    fix: str                # 能推出的修复


CLAIMS = [
    Claim("AI 不稳定", None, "无", "换更强的模型 / 调 temperature"),
    Claim("应该是模型的问题", None, "无", "改 prompt、加 few-shot"),
    Claim(
        "检索到了过期文档",
        "retrieval",
        "top-1 = c8812（2025-06 版），相似度 0.94，新版 c9901 排第 2",
        "文档加 effective_date，索引时按时间过滤；旧版标 archived",
    ),
    Claim(
        "上下文被挤掉了",
        "context",
        "输入 7,812 token，预算 8,000；例外句在第 5 节，已被截断",
        "调预算分配：例外和定义优先，历史对话降级",
    ),
]


def score(c: Claim) -> tuple[str, str]:
    """三档：可执行 / 疑似 / 不可执行。"""
    if c.span and c.evidence != "无":
        return "✅ 可执行", f"照 {c.span} 这个 span 去查"
    if c.span:
        return "⚠️ 疑似", "有方向但没证据，先去 trace 里翻这一层"
    return "❌ 不可执行", "没有 span = 没有起点，写下来的修复都是猜"


def main() -> None:
    print("=" * 84)
    print("四种\"根因\"说法，能不能推出可执行的修复")
    print("=" * 84)
    print(f"{'说法':<22}{'指向 span':<11}{'判定':<12}{'能推出的动作'}")
    print("-" * 84)
    for c in CLAIMS:
        verdict, why = score(c)
        print(f"{c.text:<22}{(c.span or '—'):<11}{verdict:<12}{c.fix}")

    print("\n" + "=" * 84)
    print("为什么前两条推不出东西")
    print("=" * 84)
    print("  · 'AI 不稳定'是**症状的同义反复**——它和'它出错了'说的是同一件事。")
    print("  · '应该是模型的问题'是**猜测**。而且这个猜测错得很有规律：")
    print("    在我处理过的案例里，大多数'模型答错'实际是检索错了或上下文被截断。")
    print("  → 按这两条去修，你会花两天调 prompt，然后发现病根在索引。")

    print("\n" + "=" * 84)
    print("同一件事，三种写法的后果")
    print("=" * 84)
    print("  'AI 不稳定'          → 换模型（贵 3 倍，问题依旧）")
    print("  '检索到了过期文档'    → 加时间过滤（一次修好，且能防复发）")
    print("  '上下文被挤掉了'      → 调预算分配（顺带修复其他三处同类问题）")
    print("\n  区别不在'写得好不好看'，在**能不能被验证**。")
    print("  能被验证的说法 → 改完能测；不能被验证的说法 → 改完只能感觉。")

    print("\n" + "=" * 84)
    print("下一级：把\"能验证\"变成一道自动体检")
    print("=" * 84)
    print("  一份复盘必须同时有：五问齐全 + trace 证据 + 行动项 + 新增评测用例 + 失败分类。")
    print("  缺一项，就不许归档——因为缺的那一项，正好是'下次不会再犯'的保证。")


if __name__ == "__main__":
    main()
