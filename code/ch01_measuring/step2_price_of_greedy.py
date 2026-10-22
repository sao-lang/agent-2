"""第 1 章 step2：一个"看起来便宜"的优化，实际怎么把账单翻倍（离线）。

运行：
    python code/ch01_measuring/step2_price_of_greedy.py

上一级的痛点：知道每步花了多少，但不知道**哪个改动会让它变贵**。

这一级做什么：做四组对照，每组只改一个变量，看成本怎么动。
所有数字都能手算复核——这才是"可争论的成本"，而不是感觉。

  ① 同一段内容：放 input 还是放 output？      → 输出贵 4 倍
  ② 同一句要求：「详细解释」vs「一句话」      → output 翻倍
  ③ 多轮对话：全量历史 vs 只带最近 3 轮       → input 累加
  ④ 重试：track 放重试内层 vs 外层             → 漏记 vs 记全
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.meter import CallRecord, Meter, price_of  # noqa: E402

MODEL = "deepseek-chat"
PIN, POUT = price_of(MODEL)

# 中文 1 字 ≈ 0.7 token（与 growth_curve.py 同一口径）
def tok(chars: int) -> int:
    return int(chars * 0.7)


def money(rec: CallRecord) -> str:
    return f"¥{rec.cost:.6f}"


def main() -> None:
    print("=" * 74)
    print(f"单价：{MODEL} 输入 ¥{PIN}/M  输出 ¥{POUT}/M   → 输出是输入的 {POUT / PIN:.0f} 倍")
    print("=" * 74)

    print("\n① 同一段 1000 字的内容：放 input 还是放 output")
    same_in = CallRecord(model=MODEL, input_tokens=tok(1000), output_tokens=0)
    same_out = CallRecord(model=MODEL, input_tokens=0, output_tokens=tok(1000))
    print(f"    放进 input ：{same_in.input_tokens:>5} token  {money(same_in)}")
    print(f"    放进 output：{same_out.output_tokens:>5} token  {money(same_out)}")
    print(f"    → 同样 1000 字，输出是输入的 {same_out.cost / max(same_in.cost, 1e-12):.1f} 倍。")
    print("      所以'让模型把原文复述一遍再回答'是这本书里最贵的坏习惯。")

    print("\n② 同一个问题：「详细解释」vs「一句话」")
    short = CallRecord(model=MODEL, input_tokens=tok(50), output_tokens=tok(30))
    long = CallRecord(model=MODEL, input_tokens=tok(50), output_tokens=tok(600))
    print(f"    一句话：out={short.output_tokens:>4} token  {money(short)}")
    print(f"    详细版：out={long.output_tokens:>4} token  {money(long)}")
    print(f"    → 输入完全一样，成本差 {long.cost / short.cost:.1f} 倍。")
    print("      这不是'模型定价不合理'，是你在为'生成'付钱。")

    print("\n③ 十轮对话：全量历史 vs 只带最近 2 轮")
    history_chars = 0
    full_cost = win_cost = 0.0
    rows = []
    for turn in range(1, 11):
        q, a = tok(30), tok(200)
        full_in = history_chars + q
        win_in = min(history_chars, tok(200 * 2)) + q       # 只留最近 2 轮问答
        full_cost += CallRecord(model=MODEL, input_tokens=full_in, output_tokens=a).cost
        win_cost += CallRecord(model=MODEL, input_tokens=win_in, output_tokens=a).cost
        rows.append((turn, full_in, win_in))
        history_chars = full_in + a
    print(f"    {'轮次':>4}{'全量 input':>12}{'窗口 input':>12}")
    for turn, f, w in rows:
        print(f"    {turn:>4}{f:>12}{w:>12}")
    print(f"    十轮总成本：全量 {full_cost:.6f}  窗口 {win_cost:.6f}  （省 {1 - win_cost / full_cost:.0%}）")
    print("    → 记住这个数字：**省的钱不是白来的**，窗口会丢掉早期事实（第 17 章）。")

    print("\n④ 重试：track 放外层还是内层")
    calls = 3      # 失败了 3 次才成功
    inner = Meter()
    for _ in range(calls):
        with inner.track(MODEL, step="answer") as rec:
            rec.input_tokens, rec.output_tokens = tok(3000), tok(50)
    outer = Meter()
    with outer.track(MODEL, step="answer") as rec:      # 只包一层 = 只记 1 次
        for _ in range(calls):
            pass
        rec.input_tokens, rec.output_tokens = tok(3000), tok(50)
    print(f"    track 在重试内层：记 {len(inner.records)} 条，¥{sum(r.cost for r in inner.records):.6f}  ← 真实成本")
    print(f"    track 在重试外层：记 {len(outer.records)} 条，¥{sum(r.cost for r in outer.records):.6f}  ← 只有 1/{calls}")
    print("    → 账单对不上时，第一个该查的地方：**计量器是不是包在重试外面**。")

    print("\n" + "=" * 74)
    print("四个数字，一句话")
    print("=" * 74)
    print(f"  · 输出比输入贵 {POUT / PIN:.0f} 倍")
    print(f"  · 「详细解释」让成本变成 {long.cost / short.cost:.1f} 倍")
    print(f"  · 滑动窗口能省 {1 - win_cost / full_cost:.0%} 的 input，代价是丢历史")
    print("  · 重试 3 次只记 1 次 = 成本被低估 67%")
    print("\n  下一级：把这四个数字变成**每次调用都自动记录**，")
    print("  而不是每次靠手算。")


if __name__ == "__main__":
    main()
