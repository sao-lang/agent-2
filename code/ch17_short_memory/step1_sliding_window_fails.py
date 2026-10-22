"""第 17 章 step1：滑窗为什么会把人"聊丢"（离线，10 秒出结果）。

运行：
    python code/ch17_short_memory/step1_sliding_window_fails.py

上一级的痛点：无（这是起点）。
这一级做什么：证明"只保留最近 N 轮"这件事，在真实对话里一定会出错。

这是全章的第一个实验。它只用 15 行代码：
  造一段 13 轮对话 → 前面藏 5 个事实 → 用预算 120 token 的滑窗一裁 → 看还剩几个。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import compress_sliding, est_tokens  # noqa: E402

# 前 3 轮埋事实，中间 7 轮闲聊，最后 3 轮回到任务本身
DIALOG: list[tuple[str, str]] = [
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

# 5 个"用户早说过、后面一定用得到"的事实
FACTS = {
    "姓名": "张伟",
    "城市": "杭州",
    "订单号": "A12345",
    "预算": "500",
    "商品": "蓝牙耳机",
}


def to_messages() -> list[dict]:
    msgs: list[dict] = []
    for u, a in DIALOG:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    return msgs


def main() -> None:
    msgs = to_messages()
    full_text = "\n".join(m["content"] for m in msgs)
    full_tokens = est_tokens(full_text)

    print("=" * 76)
    print("实验：只保留最近的内容，会发生什么")
    print("=" * 76)
    print(f"对话：{len(DIALOG)} 轮 / {len(msgs)} 条消息")
    print(f"全量历史：{full_tokens} token")
    print(f"埋下的事实：{', '.join(FACTS.values())}\n")

    print(f"{'预算(token)':>12}{'保留条数':>10}{'实际token':>12}{'事实保留':>10}   丢了哪些")
    print("-" * 80)

    for budget in (400, 250, 120, 60):
        kept = compress_sliding(msgs, budget)
        text = "\n".join(m["content"] for m in kept)
        found = [k for k, v in FACTS.items() if v in text]
        lost = [FACTS[k] for k in FACTS if k not in found]
        print(
            f"{budget:>12}{len(kept):>10}{est_tokens(text):>12}"
            f"{len(found) / len(FACTS):>9.0%}   {', '.join(lost) if lost else '—'}"
        )

    print("\n" + "=" * 76)
    print("结论")
    print("=" * 76)
    kept = compress_sliding(msgs, 120)
    text = "\n".join(m["content"] for m in kept)
    found = [k for k, v in FACTS.items() if v in text]
    lost = [FACTS[k] for k in FACTS if k not in found]
    print(f"  预算 120 时只保住 {len(found)}/{len(FACTS)} 个事实，丢了：{', '.join(lost)}")
    print()
    print("  在客服场景里，这等于「不记得客户是谁、买了什么、订单号多少」。")
    print("  用户每问一句都要重新报一遍，体验直接崩。")
    print()
    print("  但注意：滑窗**不是错的**。它高效、简单、可预测。")
    print("  错的是「用它来处理所有历史」——")
    print("  里面既有『永远不能丢的』，也有『丢了无所谓的』。")

    print("\n" + "=" * 76)
    print("  所以要问的问题不是「用什么压缩算法」，而是：")
    print("  这段对话里，哪些内容属于「不能丢」？")
    print("=" * 76)
    print("  下一级就把它们单独拎出来，放进一个**永不淘汰**的地方。")


if __name__ == "__main__":
    main()
