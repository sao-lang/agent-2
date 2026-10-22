"""第 57 章示例 2：多轮对话的 token 增长曲线（不需要 API）。

这个脚本用**估算 token 数**（中文约 1 字 ≈ 0.7 token，英文约 4 字符 ≈ 1 token），
可以离线跑，用来直观感受"为什么第 20 轮那么贵"。

运行：
    python code/ch37_measuring/growth_curve.py
"""
from __future__ import annotations

import random


def est_tokens(text: str) -> int:
    """粗略估算：中文按 0.7，其他按 1/4 字符。够用，不需要 tiktoken。"""
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cn
    return int(cn * 0.7 + other / 4) + 1


def simulate(turns: int = 20, avg_user: int = 30, avg_assistant: int = 200) -> list[dict]:
    """模拟 20 轮对话，每轮的 input token 都包含前面所有内容。"""
    history_tokens = 0
    rows = []
    for i in range(1, turns + 1):
        u = est_tokens("问" * avg_user)
        a = est_tokens("答" * avg_assistant)
        # 本轮的 input = 历史 + 本轮提问 + 系统提示（固定约 100 token）
        input_tokens = history_tokens + u + 100
        rows.append({"turn": i, "input": input_tokens, "output": a})
        history_tokens = input_tokens + a
    return rows


def compare_strategies(rows: list[dict], keep: int = 6) -> None:
    """对比三种历史管理策略的累计 input token。"""
    total_full = sum(r["input"] for r in rows)

    # 策略 B：滑动窗口，只保留最近 keep 轮
    win = 0
    total_window = 0
    for i, r in enumerate(rows):
        if i < keep:
            win = r["input"]
        else:
            # 丢掉最早的一轮（用户+助手），保持窗口大小
            win = win - rows[i - keep]["output"] - 30 + r["output"]
        total_window += win

    # 策略 C：摘要压缩，历史压成固定 150 token
    total_summary = 0
    for r in rows:
        total_summary += min(r["input"], 150 + 100 + 30)

    print(f"{'策略':<14}{'累计 input token':>20}{'相对全量':>12}")
    print("-" * 48)
    for name, total in [("全量历史", total_full), ("滑动窗口(6轮)", total_window), ("摘要压缩", total_summary)]:
        print(f"{name:<14}{total:>20,}{total / total_full:>11.0%}")


def main() -> None:
    rows = simulate()
    print(f"{'轮次':>4}{'input':>10}{'output':>9}{'本轮 input/首轮':>18}")
    print("-" * 42)
    base = rows[0]["input"]
    for r in rows:
        print(f"{r['turn']:>4}{r['input']:>10,}{r['output']:>9,}{r['input'] / base:>17.1f}x")

    print()
    compare_strategies(rows)

    print("\n结论：")
    print("  · 全量历史下，第 20 轮的 input 是第 1 轮的十几倍（超线性）")
    print("  · 滑动窗口能把总量压到 1/3 左右，代价是**忘记早期事实**")
    print("  · 摘要压缩省得更多，但摘要本身会失真")
    print("  → 第 40 章会给一个「两者结合」的实现，并用实验证明它保住了早期事实。")


if __name__ == "__main__":
    random.seed(0)
    main()
