"""第 1 章 step2：上下文窗口——模型一次能看见多少（离线）。

运行：
    python code/ch01_llm_basics/step2_context_window.py

上一级的痛点：你觉得模型"忘事"，但不知道从哪一句开始忘。

这一级做什么：把 12 条消息塞进一个只有 8 个位置的窗口，看谁被丢掉，
然后量化"丢掉的那部分里，有多少是关键事实"。

口径说明：本例用"1 个汉字 = 1 token、英文 4 字符 = 1 token"的简化换算。
真实 token 数请用厂商返回的 usage（第 2 章会给函数）。
"""
from __future__ import annotations


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cn
    return int(cn + other / 4) + 1


MESSAGES = [
    ("user", "我叫张伟，是做物流的，人在杭州。"),
    ("assistant", "你好张伟，有什么可以帮您？"),
    ("user", "我上周买的蓝牙耳机，订单号 A12345，预算本来是 500 元以内。"),
    ("assistant", "记下了：订单 A12345，预算 500 元。"),
    ("user", "耳机右耳有滋滋声。"),
    ("assistant", "这个可能和蓝牙编解码或耳塞网罩有关，我们先排查。"),
    ("user", "你们最近有什么活动吗？"),
    ("assistant", "本月满 300 减 30，会员额外 9 折。"),
    ("user", "那会员退货时优惠券还退吗？"),
    ("assistant", "已使用的优惠券不返还。"),
    ("user", "我这个滋滋声能换新吗？"),
    ("assistant", "需要先排查，判定为硬件故障可以换新。"),
]

FACTS = {"订单号": "A12345", "预算": "500", "城市": "杭州", "故障": "滋滋声"}


def window(messages: list[tuple[str, str]], budget: int) -> tuple[list[tuple[str, str]], int]:
    """从最新往回装，装不下就停。返回 (保留的消息, 被丢掉的条数)。"""
    kept: list[tuple[str, str]] = []
    used = 0
    for role, text in reversed(messages):
        cost = est_tokens(text) + 4          # +4 是每条消息的固定开销（role/分隔符）
        if used + cost > budget:
            break
        used += cost
        kept.append((role, text))
    kept.reverse()
    return kept, len(messages) - len(kept)


def main() -> None:
    total = sum(est_tokens(t) + 4 for _, t in MESSAGES)
    print("=" * 76)
    print("上下文窗口：模型一次能看见多少")
    print("=" * 76)
    print(f"12 条消息合计约 {total} token；其中含 {len(FACTS)} 个关键事实：{', '.join(FACTS.values())}\n")

    print(f"{'窗口':>6}{'保留条数':>9}{'保留 token':>11}{'事实保留':>9}   丢了哪些事实")
    print("-" * 76)
    for budget in (200, 120, 80, 50, 30):
        kept, dropped = window(MESSAGES, budget)
        text = "".join(t for _, t in kept)
        found = [k for k, v in FACTS.items() if v in text]
        lost = [FACTS[k] for k in FACTS if k not in found]
        used = sum(est_tokens(t) + 4 for _, t in kept)
        print(f"{budget:>6}{len(kept):>9}{used:>11}{len(found) / len(FACTS):>8.0%}   {', '.join(lost) or '—'}")

    print("-" * 76)
    kept, dropped = window(MESSAGES, 80)
    print(f"\n窗口=80 时保留了这 {len(kept)} 条：")
    for role, text in kept:
        print(f"  [{role:<9}] {text}")

    print("\n" + "=" * 76)
    print("结论")
    print("=" * 76)
    print("  · 「忘事」不是模型的 bug，是窗口装不下。")
    print("  · 谁被丢掉，取决于你的策略：本例是「保最新」，所以最早说的事实最先没了。")
    print("  · 更麻烦的是：模型不知道自己被截了——它会用剩下的内容硬答。")
    print()
    print("  所以真正的问题不是「窗口多大」，而是：")
    print("  **这一堆内容里，哪几条永远不能丢？**")
    print("  → 第 26 章（短期记忆）会给答案：把「不能丢的」放进槽位，其余随意裁。")


if __name__ == "__main__":
    main()
