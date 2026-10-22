"""第 27 章 step3：情景记忆 —— 只增不改，但要按时间衰减。

运行：
    python code/ch27_long_memory/step3_episodic.py

上一级的痛点：语义记忆解决了"用户是什么样"，但"发生过什么"还没地方放。
这一级做什么：用一条打分公式，让你看见"三个月前"和"昨天"的差距，
             并证明**半衰期选错会让你把旧事件当现状**。

score = importance × 0.5^(age_days / halflife_days) × (1 + ln(1 + use_count))
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.long_memory import Memory, MemoryKind, MemoryStore, score_memory  # noqa: E402

SCOPE = {"tenant_id": "shop-1", "user_id": "u-zhang"}

# (天数, 内容, 重要性)
EVENTS = [
    (0, "今天投诉了运费问题", 0.8),
    (1, "确认了收件地址", 0.5),
    (7, "咨询过运费规则", 0.5),
    (60, "问过会员权益", 0.5),
    (120, "问过发票怎么开", 0.4),
]


def build(days: int, content: str, importance: float) -> Memory:
    return Memory(
        id=f"epi-{days}",
        kind=MemoryKind.EPISODIC,
        key="",
        content=content,
        importance=importance,
        created_at=time.time() - days * 86400,
        **SCOPE,
    )


def main() -> None:
    store = MemoryStore()
    mems = [build(*e) for e in EVENTS]
    for m in mems:
        store.write(m)

    now = time.time()
    print("=" * 84)
    print("同一批事件，三种半衰期下的排序")
    print("=" * 84)
    print(f"{'事件':<24}{'天数':>6}" + "".join(f"{f'半衰期{h}天':>14}" for h in (7, 30, 365)))
    print("-" * 84)
    for m in mems:
        age = int((now - m.created_at) / 86400)
        cells = f"{score_memory(m, now, 7.0):>14.3f}{score_memory(m, now, 30.0):>14.3f}{score_memory(m, now, 365.0):>14.3f}"
        print(f"{m.content:<24}{age:>6}{cells}")

    print("\n" + "=" * 84)
    print("关键对比：『60 天前问过会员权益』和『今天投诉运费』的分数比")
    print("=" * 84)
    old_m = next(m for m in mems if m.content == "问过会员权益")
    new_m = next(m for m in mems if m.content == "今天投诉了运费问题")
    for hl in (7.0, 30.0, 365.0):
        ratio = score_memory(old_m, now, hl) / score_memory(new_m, now, hl)
        print(f"  半衰期 {hl:>5.0f} 天：老事件/新事件 = {ratio:>6.3f}"
              f"   {'（几乎被淹没）' if ratio < 0.2 else '（仍具竞争力）' if ratio > 0.5 else ''}")
    print()
    print("  → 同一份数据，只改半衰期，『旧事件还能不能被想起』天差地别。")
    print("    这就是为什么半衰期是**业务决策**，不是技术参数。")

    print("\n" + "=" * 84)
    print("为什么半衰期必须按业务定")
    print("=" * 84)
    print("  客服场景（半衰期 7 天）：用户状态变化快，上周的抱怨不该影响今天的接待。")
    print("  医疗场景（半衰期 365 天）：三年前的过敏史，今天依然致命。")
    print("  法务场景（不衰减）：判例永远有效，越老越权威。")
    print()
    print("  选错的后果不是『排序不好看』，而是**把旧事件当成现状**：")
    print("    半衰期 365 天 + 客服场景 → 三个月前问过会员权益的用户，")
    print("    今天一来就被推荐会员套餐，而他上个月已经退订了。")

    print("\n" + "=" * 84)
    print("公式里三个因子各管一件事")
    print("=" * 84)
    print("  importance ：这件事本身有多重要（写入时定的）")
    print("  0.5^(age/hl)：时间衰减。hl=30 时，每过 30 天分数减半")
    print("  1+ln(1+use)：被反复用到的事件更容易被再次想起")
    print()
    m = mems[0]
    for n in (0, 1, 5, 20):
        m.use_count = n
        s = score_memory(m, now, 30.0)
        print(f"    use_count={n:<3} → 分数 {s:.3f}（频率因子 {1 + math.log1p(n):.2f}）")

    print("\n  → 注意：频率因子是**线性增长**的，但时间衰减是**指数下降**的。")
    print("     所以一条被用了 20 次、但已经放了 1 年的记忆，")
    print("     依然打不过一条刚发生、只用过 1 次的事件。这通常是对的。")

    print("\n" + "=" * 84)
    print("结论")
    print("=" * 84)
    print("  情景记忆只增不改（它是『历史』，不是『现状』）。")
    print("  但检索时必须乘一个时间因子，否则历史会淹没现状。")


if __name__ == "__main__":
    main()
