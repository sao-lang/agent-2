"""上下文窗口溢出时，丢的是什么、丢在哪。

不联网。用固定数值演示两种溢出方式：
  1. 请求被拒（输入 + 预留输出超过窗口）
  2. 生成中途被截断（finish_reason=length）

并演示"预留输出"这个选择如何影响可用输入空间。
"""

from __future__ import annotations

WINDOW = 8192


def check(prompt_tokens: int, max_tokens: int) -> tuple[str, int, str]:
    """返回 (结果, 剩余可用, 说明)。"""
    need = prompt_tokens + max_tokens
    if need > WINDOW:
        return "请求被拒", 0, f"{prompt_tokens}+{max_tokens}={need} > {WINDOW}"
    return "可以开始", WINDOW - need, f"剩余 {WINDOW - need}"


def build_history(system: int, docs: list[int], dialog: int) -> list[tuple[str, int]]:
    """构造 messages，并标出每一部分的 token 占用。"""
    parts = [("系统提示", system)]
    for i, d in enumerate(docs, 1):
        parts.append((f"检索文档{i}", d))
    parts.append(("对话历史", dialog))
    return parts


def trim_to_fit(parts: list[tuple[str, int]], budget: int) -> tuple[list[tuple[str, int]], list[str]]:
    """按从后往前的顺序丢弃，记录丢了什么。只演示"整段丢弃"这一种做法。"""
    kept = list(parts)
    dropped: list[str] = []
    total = sum(t for _, t in kept)

    # 先丢最早的检索文档
    while total > budget and any(n.startswith("检索文档") for n, _ in kept):
        idx = next(i for i, (n, _) in enumerate(kept) if n.startswith("检索文档"))
        total -= kept[idx][1]
        dropped.append(kept[idx][0])
        del kept[idx]

    return kept, dropped


def main() -> None:
    print(f"窗口 = {WINDOW}")
    print()

    print("预留输出对可用输入的影响：")
    print(f"{'max_tokens':>12}{'可用输入':>10}  结果")
    for mt in (256, 1024, 2048):
        _, remain, _ = check(4000, mt)
        print(f"{mt:>12}{WINDOW - mt:>10}  输入 4000 时{check(4000, mt)[0]}")
    print()

    parts = build_history(system=300, docs=[2400, 3200, 2800], dialog=1400)
    total = sum(t for _, t in parts)
    print("一份完整的上下文：")
    for name, t in parts:
        print(f"  {name:<12}{t:>6}")
    print(f"  {'合计':<12}{total:>6}")

    budget = WINDOW - 1024
    print()
    print(f"预留输出 1024，可用输入 {budget}，溢出 {total - budget}")
    kept, dropped = trim_to_fit(parts, budget)
    print(f"  丢掉了：{dropped}")
    print(f"  剩余 {sum(t for _, t in kept)}")

    print()
    print("这里丢的是整段文档。丢掉的代价：")
    print("  如果答案在那段文档里，这次生成必然答不出来。")
    print("  而调用方看不到这个丢失，只能看到答案错了。")
    print()
    print("另一种做法是单条消息级截断（截断长文档的后半段），")
    print("保留每段的前面部分。代价不同：它不会整段消失，但可能截在半句上。")
    print()
    print("溢出的两种形态要分开：")
    print("  请求被拒：没有开始生成，拿不到任何文本，也没有 finish_reason")
    print("  length  ：生成到一半停止，拿到部分文本，finish_reason=length")


if __name__ == "__main__":
    main()
