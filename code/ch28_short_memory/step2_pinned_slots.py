"""第 27 章 step2：只加一个概念 —— 固定槽位（永不淘汰的那几个字段）。

运行：
    python code/ch28_short_memory/step2_pinned_slots.py

上一级的痛点：滑窗把"张伟 / 杭州 / 500"全丢了。
这一级做什么：在历史之外，单独维护一张**键值小表**，它永远完整地进上下文。

核心只有三行逻辑：
  1. 每轮从用户消息里尝试填槽（正则）
  2. 填过的槽**不会被历史压缩影响**
  3. 组装上下文时，槽位作为第一条 system 消息放在最前面

同时演示它的两个真实风险：误捕获、改口不生效。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import compress_sliding, est_tokens  # noqa: E402
from common.short_memory import Slots  # noqa: E402

DIALOG: list[tuple[str, str]] = [
    ("我叫张伟，是做物流的，人在杭州。", "你好张伟，很高兴认识你。"),
    ("订单号 A12345，上周买的蓝牙耳机，预算本来 500 元以内。", "记下了订单 A12345，预算 500 元。"),
    ("我主要担心右耳有滋滋声。", "这个我会重点帮你看。"),
    *[(f"顺便问下你们最近有什么活动（第 {i} 次问）？", "本月满 300 减 30，会员额外 9 折。") for i in range(7)],
    ("我买的是哪款来着？", "你买的是上周那单蓝牙耳机（订单 A12345）。"),
    ("那我这个滋滋声能换新吗？", "需要先排查，硬件问题可换新。"),
    ("好的，那帮我看看流程。", "App - 我的订单 - 申请售后 - 选择换新。"),
]

FACTS = {"姓名": "张伟", "城市": "杭州", "订单号": "A12345", "预算": "500", "商品": "蓝牙耳机"}


def run(budget: int) -> tuple[str, dict[str, str]]:
    """跑一遍对话，返回（拼好的上下文文本, 最终槽位）。"""
    slots = Slots()
    msgs: list[dict] = []
    for user, assistant in DIALOG:
        slots.capture(user)  # ① 每轮尝试填槽
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": assistant})

    recent = compress_sliding(msgs, budget)  # ② 历史照常压缩
    parts = [slots.render()] + [m["content"] for m in recent]  # ③ 槽位固定在最前
    return "\n".join(p for p in parts if p), slots.values


def main() -> None:
    print("=" * 78)
    print("只加一个概念：把「不能丢的」单独存起来")
    print("=" * 78)
    text, values = run(120)
    print("槽位捕获结果：")
    for k, v in values.items():
        print(f"    {k:<10} = {v}")

    found = [k for k, v in FACTS.items() if v in text]
    slot_tokens = est_tokens("\n".join(f"- {k}: {v}" for k, v in values.items()))
    print(f"\n预算 120 下的事实保留：{len(found)}/{len(FACTS)}  →  {found}")
    print(f"上下文 token：{est_tokens(text)}（其中槽位只占 {slot_tokens}）")
    print()
    print("  5 个事实全在，但槽位总共只占 22 个 token —— 历史占的是 100+。")
    print("  花 22 个 token 换「永远记得客户是谁」，这是整章最划算的一笔交易。")

    print("\n" + "=" * 78)
    print("为什么这一步就够了")
    print("=" * 78)
    print("  滑窗丢事实，是因为事实和历史**混在同一个池子里**，")
    print("  而池子有上限，早期内容注定被挤掉。")
    print()
    print("  槽位把 5 个字段拎出来单独存，占几十个 token，")
    print("  无论聊 13 轮还是 1300 轮，它们都在。")
    print()
    print("  这不是「更好的压缩算法」，是**换了一个存放位置**。")

    print("\n" + "=" * 78)
    print("但这个方案有两个真实的坑（下一级会逐个处理）")
    print("=" * 78)

    # 坑 1：误捕获
    bad = Slots()
    updated = bad.capture("我叫他帮我看看这个订单")
    print("  坑 1 · 误捕获")
    print("    输入：我叫他帮我看看这个订单")
    print(f"    结果：{bad.values}  （触发了 {updated}）")
    print("    → 把「他帮」当成了用户的名字")

    # 坑 2：改口不生效
    bad2 = Slots()
    bad2.capture("订单号 A12345，上周买的蓝牙耳机")
    before = dict(bad2.values)
    bad2.capture("订单号改成 B67890")
    print("\n  坑 2 · 改口不生效")
    print(f"    第一句后：order_id = {before.get('order_id')}")
    print(f"    「订单号改成 B67890」后：order_id = {bad2.values.get('order_id')}")
    print("    → 用户明确改口了，但槽位拒绝更新")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  槽位的价值 = 把「永不淘汰」和「滚动淘汰」分开。")
    print("  槽位的代价 = 需要一套**捕获 + 纠错**机制，而正则做不好这件事。")
    print("  下一级：换一种捕获方式 —— 不再靠正则，让模型按 schema 抽。")


if __name__ == "__main__":
    main()
