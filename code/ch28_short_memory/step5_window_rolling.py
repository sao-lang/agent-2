"""第 27 章 step5：会话窗口怎么滚才不切散对话。

运行：
    python code/ch28_short_memory/step5_window_rolling.py

上一级的痛点：预算终于守住了，但你可能没注意 —— 保留下来的消息可能"没头没尾"。
这一级做什么：对比三种滚动方式，让你看见"窗口起点不对齐"这个坑。

三种方式：
  A. 按条数：留最近 N 条（最朴素，最容易切散）
  B. 按 token：留最近 N token（第 25 章的做法，仍然会切散）
  C. 按问答对：窗口起点必须落在 user 消息上（本级的方案）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import compress_sliding, est_tokens  # noqa: E402

# 这段对话故意设计成：一条 assistant 很长，一条 user 很短
DIALOG: list[tuple[str, str]] = [
    ("我的耳机有杂音", "是左耳还是右耳？"),
    ("右耳", "好的。右耳电流声常见原因有三种：蓝牙编解码不匹配、耳塞网罩堵塞、电池老化。"
            "建议按顺序排查：第一步重置耳机，第二步换设备测试，第三步清洁网罩。"),
    ("嗯", "需要我帮你走换新流程吗？"),
    ("要", "好的，App - 我的订单 - 申请售后 - 选择换新。"),
    ("那运费谁出", "非人为质量问题往返运费由商家承担；人为损坏则由买家承担，并需支付检测费 20 元。"),
    ("好的，谢谢", "不客气。"),
]


def to_messages() -> list[dict]:
    msgs: list[dict] = []
    for u, a in DIALOG:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    return msgs


def by_count(msgs: list[dict], n: int) -> list[dict]:
    return msgs[-n:]


def by_tokens(msgs: list[dict], budget: int) -> list[dict]:
    return compress_sliding(msgs, budget)


def by_turns(msgs: list[dict], budget: int) -> list[dict]:
    """按 token 装，但**窗口起点必须对齐到 user 消息**。

    做法：先按 token 从后往前装，然后把开头连续的 assistant 消息丢掉——
    因为"没有问题的回答"对模型是噪音。
    """
    kept = compress_sliding(msgs, budget)
    while kept and kept[0]["role"] != "user":
        kept = kept[1:]
    return kept


def show(label: str, msgs: list[dict], budget: int) -> None:
    text = "\n".join(m["content"] for m in msgs)
    tok = est_tokens(text)
    ok = "OK " if tok <= budget else "超! "
    first_role = msgs[0]["role"] if msgs else "-"
    align = "对齐" if first_role == "user" else "错位"
    print(f"  {label:<12}{len(msgs):>4} 条{tok:>6} token  {ok}起点={first_role:<10}{align}")


def main() -> None:
    msgs = to_messages()
    budget = 51
    full = est_tokens("\n".join(m["content"] for m in msgs))

    print("=" * 78)
    print("同一段对话，三种滚动方式")
    print("=" * 78)
    print(f"全量：{len(msgs)} 条 / {full} token。目标预算：{budget} token\n")

    a1 = by_count(msgs, 4)
    b1 = by_tokens(msgs, budget)
    c1 = by_turns(msgs, budget)
    show("A 按条数(4)", a1, 10**9)
    show("B 按token", b1, budget)
    show("C 按轮次对齐", c1, budget)

    print("\n" + "=" * 78)
    print("坑：窗口起点落在 assistant 上会怎样")
    print("=" * 78)
    for label, kept in (("A 按条数", a1), ("B 按token", b1), ("C 对齐", c1)):
        print(f"  {label} 保留下来的完整窗口：")
        for m in kept:
            print(f"    [{m['role']:<9}] {m['content'][:52]}")
        print()
    if b1 and b1[0]["role"] == "assistant":
        print("  → B 的第一句是一个**没有问题的回答**，模型只能猜「用户在问什么」。")
    print("  → C 检测到起点不是 user，主动丢掉了那条 assistant：宁可少一轮，不留半截对话。")
  

    print("\n" + "=" * 78)
    print("为什么「按条数」最危险")
    print("=" * 78)
    print("  一条消息可能是 2 个字（『嗯』），也可能是 200 个字（上面那条排查说明）。")
    print(f"  本段对话里，最长一条 {max(est_tokens(m['content']) for m in msgs)} token，"
          f"最短一条 {min(est_tokens(m['content']) for m in msgs)} token —— 差 "
          f"{max(est_tokens(m['content']) for m in msgs) // max(min(est_tokens(m['content']) for m in msgs), 1)} 倍。")
    print()
    print("  按条数留 3 条，有时只剩 10 token，有时要 300 token —— **完全不可预测**。")
    print("  而你的预算是按 token 算的，不是按条数算的。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  会话窗口的三条规则：")
    print("    1. 按 token 计量（不是按条数）")
    print("    2. 窗口起点对齐到 user 消息")
    print("    3. 装不下就停，不要为了凑满而截断一条消息")
    print()
    print("  第 3 条的理由：一条被截断的 assistant 回答，比没有它更糟 ——")
    print("  模型会以为「话说完了」，于是接着往下编。")


if __name__ == "__main__":
    main()
