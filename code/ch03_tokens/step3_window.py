"""第 3 章 step3：上下文窗口溢出（离线可运行）。

运行：
    python code/ch03_tokens/step3_window.py

本文件演示三件事：
    1. 窗口记账要包含输出预留，否则请求会被拒绝
    2. 溢出时不同裁剪策略丢弃的内容不同
    3. 丢弃顺序决定了哪些信息会丢失

token 计数使用 tiktoken，可复现。
"""

from __future__ import annotations

import sys

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")


def ntok(text: str) -> int:
    return len(ENC.encode(text))


def build_history(turns: int) -> list[dict]:
    """构造多轮对话。每轮包含一条用户消息和一条助手消息。"""
    out = []
    for i in range(1, turns + 1):
        out.append({"role": "user", "content": f"第 {i} 轮：我想咨询订单 A{1000 + i} 的退货问题。"})
        out.append({"role": "assistant", "content": f"第 {i} 轮答复：签收后七天内可以申请无理由退货。"})
    return out


SYSTEM = "你是售后助手。回答需基于提供的资料，不得编造。"

# 三种裁剪策略
def trim_drop_oldest(msgs: list[dict], budget: int) -> list[dict]:
    """从头丢，保留最近的消息。"""
    out = list(msgs)
    while sum(ntok(m["content"]) for m in out) > budget and out:
        out.pop(0)
    return out


def trim_drop_middle(msgs: list[dict], budget: int) -> list[dict]:
    """保留首尾，从中间丢。"""
    out = list(msgs)
    while sum(ntok(m["content"]) for m in out) > budget and len(out) > 2:
        out.pop(len(out) // 2)
    return out


def trim_truncate_single(msgs: list[dict], budget: int) -> list[dict]:
    """逐条截断最长的一条，而非整条丢弃。"""
    out = [dict(m) for m in msgs]
    while sum(ntok(m["content"]) for m in out) > budget:
        longest = max(out, key=lambda m: ntok(m["content"]))
        if ntok(longest["content"]) <= 8:
            break
        longest["content"] = longest["content"][:-4]
    return out


STRATEGIES = [
    ("丢弃最早", trim_drop_oldest),
    ("保留首尾丢中间", trim_drop_middle),
    ("逐条截断", trim_truncate_single),
]


def main() -> None:
    window = 400          # 示例窗口大小，用作演示
    reserve_output = 100  # 为输出预留

    msgs = build_history(8)
    sys_tokens = ntok(SYSTEM) + 8
    total = sys_tokens + sum(ntok(m["content"]) for m in msgs)

    print("=" * 86)
    print("① 窗口记账")
    print("=" * 86)
    print(f"  示例窗口上限        {window}")
    print(f"  系统消息            {sys_tokens}")
    print(f"  对话历史            {total - sys_tokens}")
    print(f"  当前合计            {total}")
    print(f"  可用（扣除输出预留）  {window - reserve_output}")
    print(f"  是否超出            {'是' if total > window - reserve_output else '否'}")
    print()
    print("  注：窗口大小与预留值为演示用，不代表具体模型。")
    print("  记账时必须先扣除输出预留，否则请求会被服务端拒绝。")

    print()
    print("=" * 86)
    print("② 三种裁剪策略的结果（预算收紧到 150）")
    print("=" * 86)
    budget = 150
    for name, fn in STRATEGIES:
        kept = fn(msgs, budget)
        kept_tokens = sum(ntok(m["content"]) for m in kept)
        first = kept[0]["content"][:18] if kept else ""
        last = kept[-1]["content"][:18] if kept else ""
        print(f"\n  【{name}】保留 {len(kept)}/{len(msgs)} 条，{kept_tokens} token")
        print(f"    第一条：{first}")
        print(f"    最后一条：{last}")

    print()
    print("=" * 86)
    print("③ 每种策略丢掉的是什么")
    print("=" * 86)
    rows = [
        ("丢弃最早", "开头的对话，通常包含任务前提与约束", "最近的上下文完整"),
        ("保留首尾丢中间", "中段对话，可能是关键约束所在", "开头结尾都在"),
        ("逐条截断", "每条末尾几个字", "消息条数不变，内容不完整"),
    ]
    print(f"  {'策略':<16}{'丢失内容':<34}{'保留部分'}")
    print("  " + "-" * 82)
    for a, b, c in rows:
        print(f"  {a:<16}{b:<34}{c}")

    print()
    print("  三种策略丢失的东西不同，没有一种能保证关键信息不丢。")
    print("  因此裁剪需要配合「哪些内容不能丢」的显式判断，不能只按长度处理。")

    print()
    print("=" * 86)
    print("④ 结论")
    print("=" * 86)
    print("  1. 窗口记账必须扣除输出预留")
    print("  2. 溢出时丢弃什么，取决于裁剪策略")
    print("  3. 按长度裁剪无法判断内容重要性")
    print("  4. 关键约束应放在不受裁剪影响的位置，或独立于历史保存")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
