"""第 3 章 step2：成本结构与缓存命中（离线可运行）。

运行：
    python code/ch03_tokens/step2_cost.py

本文件演示三件事：
    1. 输入与输出的单价差异如何影响总成本
    2. 多轮对话中，历史消息重复计入输入成本
    3. 缓存命中对输入成本的削减

单价为示例值，来自下方 PRICING 表，不代表任何厂商的真实价格。
使用这些数字的目的是展示计算结构，不是给出结论。
"""

from __future__ import annotations

import sys


# 示例单价（每百万 token，单位：元）
# 这些数值是构造的，用于演示计算结构。
PRICING = {
    "model-a": {"input": 2.0, "output": 8.0, "cached_input": 0.5},
}


def cost(model: str, in_tokens: int, out_tokens: int, cached: int = 0) -> dict:
    p = PRICING[model]
    fresh = max(0, in_tokens - cached)
    in_cost = fresh / 1_000_000 * p["input"] + cached / 1_000_000 * p["cached_input"]
    out_cost = out_tokens / 1_000_000 * p["output"]
    return {
        "input_tokens": in_tokens,
        "cached_tokens": cached,
        "output_tokens": out_tokens,
        "input_cost": in_cost,
        "output_cost": out_cost,
        "total": in_cost + out_cost,
    }


def main() -> None:
    model = "model-a"
    p = PRICING[model]

    print("=" * 84)
    print("① 示例单价")
    print("=" * 84)
    print(f"  输入          {p['input']:.1f} 元 / 百万 token")
    print(f"  输出          {p['output']:.1f} 元 / 百万 token")
    print(f"  缓存命中输入    {p['cached_input']:.1f} 元 / 百万 token")
    print()
    print("  注：以上为示例值，用于演示计算结构。")

    print()
    print("=" * 84)
    print("② 输入与输出各占多少成本")
    print("=" * 84)
    print(f"  {'场景':<22}{'输入':<10}{'输出':<10}{'输入成本':<12}{'输出成本':<12}{'输出占比'}")
    print("  " + "-" * 80)
    cases = [
        ("短输入长输出", 500, 1500),
        ("长输入短输出", 8000, 300),
        ("等长", 2000, 2000),
    ]
    for name, i, o in cases:
        r = cost(model, i, o)
        share = r["output_cost"] / r["total"]
        print(f"  {name:<22}{i:<10}{o:<10}{r['input_cost']:<12.6f}{r['output_cost']:<12.6f}{share:.0%}")

    print()
    print("  输出单价通常是输入单价的数倍，因此输出量对成本的影响更大。")
    print("  「长输入短输出」的场景下成本主要由输入决定。")

    print()
    print("=" * 84)
    print("③ 多轮对话：历史消息重复计入输入")
    print("=" * 84)
    print(f"  {'轮次':<8}{'本轮新增':<10}{'累计输入':<12}{'输出':<8}{'本轮成本':<12}{'累计成本'}")
    print("  " + "-" * 76)
    history = 0
    total = 0.0
    per_turn_input = 400
    per_turn_output = 200
    for turn in range(1, 7):
        history += per_turn_input
        r = cost(model, history, per_turn_output)
        total += r["total"]
        print(f"  {turn:<8}{per_turn_input:<10}{history:<12}{per_turn_output:<8}"
              f"{r['total']:<12.6f}{total:.6f}")

    print()
    print("  同样的对话内容，第 6 轮的输入是第 1 轮的 6 倍。")
    print("  历史消息被完整地重复发送，每一轮都按输入计费。")

    print()
    print("=" * 84)
    print("④ 缓存命中对输入成本的削减")
    print("=" * 84)
    print(f"  {'轮次':<8}{'无缓存':<14}{'有缓存':<14}{'差额'}")
    print("  " + "-" * 64)
    history = 0
    for turn in range(1, 7):
        prev = history
        history += per_turn_input
        no_cache = cost(model, history, per_turn_output)["total"]
        with_cache = cost(model, history, per_turn_output, cached=prev)["total"]
        print(f"  {turn:<8}{no_cache:<14.6f}{with_cache:<14.6f}{no_cache - with_cache:.6f}")

    print()
    print("  缓存命中后，前几轮的历史按更低单价计费。")
    print("  命中条件是前缀完全一致，任何一处改动都会导致后续全部失效。")

    print()
    print("=" * 84)
    print("⑤ 结论")
    print("=" * 84)
    print("  1. 输入与输出单价不同，输出占比高的场景成本结构不同")
    print("  2. 多轮对话中历史消息重复计费，输入量随轮次线性增长")
    print("  3. 缓存能降低重复部分的单价，但依赖前缀完全一致")
    print("  4. 成本要按环节归因，只统计总量无法判断钱花在哪")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
