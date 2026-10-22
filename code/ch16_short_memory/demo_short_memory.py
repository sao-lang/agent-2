"""第 16 章示例：短期记忆的三种实现，用"事实保留率"对比。

运行：
    python code/ch16_short_memory/demo_short_memory.py

三种实现：
  A. 全量历史（基准）
  B. 滑窗（第 10 章的最简版）
  C. 槽位 + 工作记忆 + 最近对话（本章的方案）

对比指标：
  · 事实保留率（5 个关键事实）
  · 上下文 token
  · 压缩率
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import compress_sliding, est_tokens  # noqa: E402
from common.short_memory import ShortTermMemory  # noqa: E402

# 20 轮对话：前 3 轮埋事实，中间 14 轮闲聊，最后 3 轮回归任务
DIALOG = [
    ("我叫张伟，是做物流的，人在杭州。", "你好张伟，很高兴认识你。"),
    ("订单号 A12345，上周买的蓝牙耳机，预算本来 500 元以内。", "记下了订单 A12345，预算 500 元。"),
    ("我主要担心右耳有滋滋声。", "这个我会重点帮你看。"),
    *[
        (f"顺便问下你们最近有什么活动（第 {i} 次问）？", "本月满 300 减 30，会员额外 9 折。")
        for i in range(7)
    ],
    ("我买的是哪款来着？", "你买的是上周那单蓝牙耳机（订单 A12345）。"),
    ("那我这个滋滋声能换新吗？", "需要先排查，硬件问题可换新。"),
    ("好的，那帮我看看流程。", "App - 我的订单 - 申请售后 - 选择换新。"),
]

FACTS = {
    "name": "张伟",
    "city": "杭州",
    "order_id": "A12345",
    "budget": "500",
    "product": "蓝牙耳机",
}


def run_full() -> tuple[str, int]:
    text = "\n".join(f"{u} | {a}" for u, a in DIALOG)
    return text, est_tokens(text)


def run_sliding(budget: int = 300) -> tuple[str, int]:
    msgs = []
    for u, a in DIALOG:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    kept = compress_sliding(msgs, budget)
    text = "\n".join(m["content"] for m in kept)
    return text, est_tokens(text)


def run_short_memory(budget: int = 300) -> tuple[str, int, dict]:
    mem = ShortTermMemory(max_tokens=budget)
    for u, a in DIALOG:
        mem.add_user(u)
        mem.add_assistant(a)
    ctx = mem.build_context()
    text = "\n".join(m["content"] for m in ctx)
    return text, est_tokens(text), mem.stats()


def check(text: str) -> list[str]:
    return [k for k, v in FACTS.items() if v in text]


def main() -> None:
    rows = []

    text_a, tok_a = run_full()
    rows.append(("A 全量历史", tok_a, tok_a, check(text_a), "—"))

    text_b, tok_b = run_sliding(120)
    rows.append(("B 滑窗(120)", tok_b, tok_b, check(text_b), "—"))

    text_c, tok_c, stats = run_short_memory(120)
    rows.append(("C 短期记忆(120)", tok_c, tok_c, check(text_c), f"{stats['compression']:.0%}"))

    print(f"对话轮数：{len(DIALOG)}    关键事实：{list(FACTS.values())}\n")
    print(f"{'方案':<18}{'上下文token':>12}{'压缩率':>8}{'事实保留':>10}   丢失的事实")
    print("-" * 88)
    for name, _, tok, found, comp in rows:
        lost = [FACTS[k] for k in FACTS if k not in found]
        print(f"{name:<18}{tok:>12}{comp:>8}{len(found) / len(FACTS):>9.0%}   {', '.join(lost) if lost else '—'}")

    print("\n" + "=" * 88)
    print("方案 C 的上下文长什么样")
    print("=" * 88)
    mem = ShortTermMemory(max_tokens=120)
    for u, a in DIALOG:
        mem.add_user(u)
        mem.add_assistant(a)
    for m in mem.build_context():
        role = m["role"]
        content = m["content"].replace("\n", " ")
        print(f"  [{role:<9}] {content[:88]}")

    print("\n" + "=" * 88)
    print("为什么 C 能保住事实（而 B 保不住）")
    print("=" * 88)
    print("  · B 滑窗：只留最近 N 条 → 前 3 轮的事实**物理上消失了**")
    print("  · C 槽位：首次捕获即固定，永不淘汰 → 无论聊多少轮，'张伟/杭州/A12345' 都在")
    print("  · C 工作记忆：当前任务/已完成/待办 是可推理的结构化状态，不占多少 token")
    print("  · C 最近对话：保证「刚才说了什么」的连贯性")
    print("\n  👉 关键设计：**把「不能丢的」和「可以丢的」分开处理**，")
    print("     而不是对整段历史用同一个策略。这就是「记忆分层」的第一层。")

    print("\n" + "=" * 88)
    print("⚠️ 槽位的风险")
    print("=" * 88)
    print("  槽位靠正则捕获，会出错：")
    print("    · '我叫他帮我看看' → 会错误捕获 name='他帮'")
    print("    · 用户改口 '订单号改成 B67890' → 默认不覆盖（需 override=True）")
    print("  生产环境建议：捕获后用**小模型确认**，或让用户在 UI 上确认槽位。")


if __name__ == "__main__":
    main()


