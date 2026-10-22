"""第 2 章 step2：token 怎么变成钱，以及为什么"省 token"经常反而更贵（离线）。

运行：
    python code/ch02_token/step2_cost.py

上一级的痛点（step1）：知道了 token 数，但 token 数本身不是决策依据——
                      "从 8000 token 降到 6000 token"听起来很好，
                      但如果同时多调了一次模型，总价反而更高。

这一级做什么：把 token 换算成钱，然后跑三个真实的取舍场景，看哪一个真的省：
  A. 输入贵 vs 输出贵的非对称
  B. 省钱手段 A：缩短输出（max_tokens）
  C. 省钱手段 B：加一轮"先摘要再回答"
  D. 省钱手段 C：命中上下文缓存

单价表直接复用 code/common/meter.py 的 PRICING，全书口径统一。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.meter import PRICING, price_of  # noqa: E402

# 一份典型的客服上下文：系统提示 + 检索到的 5 段政策 + 用户问题
SYSTEM_TOKENS = 420
RETRIEVED_TOKENS = 1_800
QUESTION_TOKENS = 30
INPUT_TOKENS = SYSTEM_TOKENS + RETRIEVED_TOKENS + QUESTION_TOKENS


def money(model: str, inp: int, out: int, cached: int = 0) -> float:
    """按 meter.py 的口径算钱（元）。缓存命中的输入 token 不计费。"""
    pin, pout = price_of(model)
    return (inp - cached) / 1e6 * pin + out / 1e6 * pout


def main() -> None:
    print("=" * 84)
    print("单价表（元 / 百万 token，来自 code/common/meter.py）")
    print("=" * 84)
    print(f"{'模型':<22}{'输入':>10}{'输出':>10}   输出/输入 倍数")
    print("-" * 84)
    for name, (pin, pout) in PRICING.items():
        ratio = f"{pout / pin:.1f}x" if pin else "—"
        print(f"{name:<22}{pin:>10.1f}{pout:>10.1f}   {ratio:>10}")
    print("-" * 84)

    model = "deepseek-chat"
    pin, pout = price_of(model)
    print(f"\n本章统一用 {model}：输入 {pin} 元/百万，输出 {pout} 元/百万 → 输出比输入贵 {pout / pin:.1f} 倍\n")

    print("=" * 84)
    print("A. 一次客服问答的账：input 2250 token，output 300 token")
    print("=" * 84)
    out_tokens = 300
    in_cost = INPUT_TOKENS / 1e6 * pin
    out_cost = out_tokens / 1e6 * pout
    total = in_cost + out_cost
    print(f"  输入 {INPUT_TOKENS:>6,} token  →  ¥{in_cost:.6f}   占 {in_cost / total:>5.1%}")
    print(f"  输出 {out_tokens:>6,} token  →  ¥{out_cost:.6f}   占 {out_cost / total:>5.1%}")
    print(f"  合计              →  ¥{total:.6f}")
    print(f"\n  输出只占 token 总量的 {out_tokens / (INPUT_TOKENS + out_tokens):.0%}，")
    print(f"  却占了成本的 {out_cost / total:.0%} —— 这就是优化要先看输出的原因。")

    print("\n" + "=" * 84)
    print("B. 省钱手段 A：把 max_tokens 从 300 压到 120")
    print("=" * 84)
    cost_b = money(model, INPUT_TOKENS, 120)
    print(f"  压输出后  ¥{cost_b:.6f}（原 ¥{total:.6f}，省 {1 - cost_b / total:.1%}）")

    print("\n" + "=" * 84)
    print("C. 省钱手段 B：先摘要再回答（多一轮调用）")
    print("=" * 84)
    # 第一轮：把 1800 token 的检索内容压成 400 token 摘要（输出 400）
    round1 = money(model, RETRIEVED_TOKENS, 400)
    # 第二轮：用摘要（400）+ 系统（420）+ 问题（30）回答，输出 300
    round2_in = SYSTEM_TOKENS + 400 + QUESTION_TOKENS
    round2 = money(model, round2_in, 300)
    cost_c = round1 + round2
    print(f"  第一轮（摘要 1800→400）  ¥{round1:.6f}")
    print(f"  第二轮（用摘要回答）     ¥{round2:.6f}")
    print(f"  合计                    ¥{cost_c:.6f}（原 ¥{total:.6f}，{'省' if cost_c < total else '多花'} {abs(1 - cost_c / total):.1%}）")
    print("  但调用次数从 1 次变成 2 次，**延迟至少翻倍**。")

    print("\n" + "=" * 84)
    print("D. 省钱手段 C：命中上下文缓存（系统提示 + 检索内容被缓存）")
    print("=" * 84)
    cached = SYSTEM_TOKENS + RETRIEVED_TOKENS
    cost_d = money(model, INPUT_TOKENS, 300, cached=cached)
    print(f"  缓存 {cached:,} token，实付输入只有 {INPUT_TOKENS - cached} token")
    print(f"  合计 ¥{cost_d:.6f}（原 ¥{total:.6f}，省 {1 - cost_d / total:.1%}）")
    print("  ⚠️ 缓存只在「前缀完全一致」时命中——system prompt 少一个字节就全部失效。")

    print("\n" + "=" * 84)
    print("四种方案横向对比")
    print("=" * 84)
    rows = [
        ("不做优化", total, 1, "基线"),
        ("压 max_tokens 300→120", cost_b, 1, "救急，但答案可能被截断"),
        ("先摘要再回答", cost_c, 2, f"{'省' if cost_c < total else '更贵'}，且延迟 ×2"),
        ("命中上下文缓存", cost_d, 1, "最划算，前提是前缀稳定"),
    ]
    print(f"{'方案':<26}{'成本':>12}{'相对基线':>10}{'调用次数':>9}   代价")
    print("-" * 84)
    for name, cost, calls, note in rows:
        print(f"{name:<26}¥{cost:>11.6f}{cost / total:>9.0%}{calls:>9}   {note}")
    print("-" * 84)

    print("\n" + "=" * 84)
    print("结论")
    print("=" * 84)
    print("  · **输出 token 比输入贵 4 倍**，所以优化第一步永远是「让输出变短」，不是「让输入变短」。")
    print("  · **多一轮调用很少真的省钱**：省下的输入钱抵不过多出的输出钱 + 多出的延迟。")
    print("    真正省钱的顺序是：缓存 > 压输出 > 减检索条数 >> 加中间轮。")
    print("  · **一次调用给不出成本，只有账本给得出**。这就是第 39 章要做的事：")
    print("    每一笔都记账，才能回答「这个月哪一步烧了 60% 的钱」。")

    assert cost_d < total, "缓存必须省钱，否则单价表算错了"


if __name__ == "__main__":
    main()
