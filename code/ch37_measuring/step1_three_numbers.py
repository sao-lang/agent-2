"""第 57 章 step1：能调通之后，第一个问题是什么（离线，5 秒出结果）。

运行：
    python code/ch37_measuring/step1_three_numbers.py

上一级的痛点：无（这是起点）。
这一级做什么：不调用任何模型，只用"一次调用会留下的三样东西"，
证明"能调通"和"能运营"之间差的是**记录**，不是能力。

三样东西就是你每次调用都能拿到、但大部分人不记的：
  input_tokens / output_tokens / 耗时
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.meter import CallRecord  # noqa: E402

# 一次"回答用户退款问题"的 Agent 运行，真实量级（第 39 章会看到它的 trace）
RUNS = [
    # (环节, input, output, 耗时ms)
    ("intent", 180, 30, 210),
    ("retrieve", 260, 40, 60),
    ("answer", 900, 600, 2400),
]


@dataclass
class Raw:
    """一个"能调通"的 Agent 只留下这个。"""

    text: str


def naive_run() -> Raw:
    """没有计量的版本：只拿到最终文本。"""
    out = ""
    for stage, tin, tout, ms in RUNS:
        time.sleep(ms / 1000 / 5)      # 缩放到 1/5，教学演示不用真的等 2.6 秒
        out += f"[{stage}]"
    return Raw(text=out)


def measured_run() -> list[CallRecord]:
    """加了计量的版本：每次调用都留一条账。"""
    recs: list[CallRecord] = []
    for stage, tin, tout, ms in RUNS:
        rec = CallRecord(model="deepseek-chat", step=stage, input_tokens=tin, output_tokens=tout)
        t0 = time.perf_counter()
        time.sleep(ms / 1000 / 5)
        rec.total_ms = (time.perf_counter() - t0) * 1000
        recs.append(rec)
    return recs


def main() -> None:
    print("=" * 72)
    print("同一次 Agent 运行，两种记录方式")
    print("=" * 72)

    raw = naive_run()
    print(f"\n【只有文本】\n  {raw.text}")
    print("  → 你拿到的是'跑完了'，仅此而已。")

    recs = measured_run()
    print("\n【带账本】")
    print(f"  {'环节':<10}{'input':>8}{'output':>8}{'耗时ms':>9}{'成本(元)':>11}")
    print("  " + "-" * 46)
    for r in recs:
        print(f"  {r.step:<10}{r.input_tokens:>8}{r.output_tokens:>8}{r.total_ms:>9.0f}{r.cost:>11.6f}")
    total_cost = sum(r.cost for r in recs)
    total_ms = sum(r.total_ms for r in recs)
    total_in = sum(r.input_tokens for r in recs)
    print("  " + "-" * 46)
    print(f"  {'合计':<10}{total_in:>8}{sum(r.output_tokens for r in recs):>8}{total_ms:>9.0f}{total_cost:>11.6f}")

    print("\n" + "=" * 72)
    print("六个问题，现在有几个能答")
    print("=" * 72)
    answers = [
        ("这次调用花了多少 token？", f"{total_in} input / {sum(r.output_tokens for r in recs)} output"),
        ("花了多少钱？", f"¥{total_cost:.6f}"),
        ("等了多久？", f"{total_ms:.0f}ms"),
        ("哪个环节最贵？", max(recs, key=lambda r: r.cost).step),
        ("哪个环节最慢？", max(recs, key=lambda r: r.total_ms).step),
        ("output 占成本的多少？", f"{sum(r.output_tokens for r in recs) * 8 / 1e6 / total_cost:.0%}"),
    ]
    for q, a in answers:
        print(f"  {q:<24} {a}")

    print("\n" + "=" * 72)
    print("结论")
    print("=" * 72)
    print("  · 这段代码没有让 Agent 变聪明一点，但它让 Agent 变得**可讨论**。")
    print("  · 三个字段（input / output / 耗时）就是全部起点——")
    print("    第 39 章的 trace、第 35 章的成本报表、第 36 章的延迟瀑布，都是在这三个字段上加维度。")
    print(f"  · 特别注意最后一题：output 只占 token 的 {sum(r.output_tokens for r in recs) / (total_in + sum(r.output_tokens for r in recs)):.0%}，却占了成本的四成以上。")
    print("    因为输出单价是输入的 4 倍（deepseek-chat：2 元 vs 8 元 / 百万 token）。")
    print("    → 下一级：为什么'话多'比'读得多'更贵。")


if __name__ == "__main__":
    main()
