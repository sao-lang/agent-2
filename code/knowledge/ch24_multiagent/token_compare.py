"""单 agent 与双 agent 的上下文成本对照。

不联网。用字符数代替 token：两端是同一段文本，比例相同，所以比较结论不变。
这里只算"每轮带进模型的上下文有多大"，它决定了输入成本与延迟。

场景：先读 20 个文件做汇总（每个 800 字符），再基于汇总回答 10 轮。
  单 agent  汇总之后，每轮都把 20 个文件带在上下文里
  双 agent  子 agent 读文件、交出 900 字符摘要；主 agent 每轮只带摘要
"""

from __future__ import annotations

SYSTEM = 200
FILE_CHARS = 800
N_FILES = 20
SUMMARY_CHARS = 900
TURN_REPLY = 200
MAX_TURNS = 10

def make_file(i: int) -> str:
    head = f"<file {i}>"
    return head + "x" * (FILE_CHARS - len(head))


FILES = [make_file(i) for i in range(N_FILES)]
SUMMARY = "分析结论：" + "y" * (SUMMARY_CHARS - 5)


def single_per_turn() -> int:
    return SYSTEM + sum(len(f) for f in FILES) + SUMMARY_CHARS


def two_main_per_turn() -> int:
    return SYSTEM + SUMMARY_CHARS


def two_sub_once() -> int:
    return SYSTEM + sum(len(f) for f in FILES) + SUMMARY_CHARS


def cumulative(turns: int, summary_chars: int) -> tuple[int, int]:
    single = turns * (SYSTEM + sum(len(f) for f in FILES) + summary_chars)
    two = (SYSTEM + summary_chars) * turns + (SYSTEM + sum(len(f) for f in FILES) + summary_chars)
    return single, two


def break_even(summary_chars: int) -> int:
    """第几轮开始双 agent 的累计更少。"""
    for turns in range(1, MAX_TURNS + 1):
        single, two = cumulative(turns, summary_chars)
        if two < single:
            return turns
    return -1


def main() -> None:
    total_files = sum(len(f) for f in FILES)
    print("=== 1. 两个设计的上下文构成（字符）===")
    print(f"  20 个文件：{total_files} 字符")
    print(f"  单 agent 每轮：{single_per_turn()}"
          f"（系统 {SYSTEM} + 文件 {total_files} + 汇总 {SUMMARY_CHARS}）")
    print(f"  双 agent 主 agent 每轮：{two_main_per_turn()}")
    print(f"  双 agent 子 agent 一次性：{two_sub_once()}")

    print()
    print("=== 2. 累计到第 N 轮 ===")
    print(f"  {'N':<4}{'单 agent':>10}{'双 agent':>12}{'差':>12}")
    for turns in (1, 2, 3, 5, 10):
        single, two = cumulative(turns, SUMMARY_CHARS)
        print(f"  {turns:<4}{single:>10}{two:>12}{two - single:>+12}")

    print()
    print("=== 3. 盈亏平衡点 ===")
    print(f"  摘要 {SUMMARY_CHARS} 字符时，第 {break_even(SUMMARY_CHARS)} 轮起双 agent 更省")
    for size in (400, 900, 4000, 8000, 16000):
        print(f"  摘要 {size:>5} 字符 -> 平衡点第 {break_even(size)} 轮")
    print("  <- 平衡点约等于 1 + 摘要/文件总量：摘要越接近文件总量，拆分越不值得")

    print()
    print("=== 4. 交接成本只有一块，是摘要 ===")
    print(f"  子 agent 读完 20 个文件花了 {two_sub_once()} 字符的上下文，")
    print("  但它只把 900 字符交出去 —— 这就是拆分唯一的收益来源")


if __name__ == "__main__":
    main()
