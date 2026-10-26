"""第 25 章 · 第 1 级：上下文窗口满了，最先被挤掉的是什么？

运行：
    python code/ch26_context/step1_overflow.py

这一级只做一件事：把"塞满就截断"这个默认行为跑给你看。

大多数人的第一版是这样写的：
  把 system + 历史 + 检索结果拼成一个字符串，然后截断到窗口大小。

问题在于**截断位置在末尾**，而检索结果通常拼在末尾 ——
于是被截掉的是**事实**，留下的是**闲聊**。
"""
from __future__ import annotations


def est_tokens(text: str) -> int:
    """粗估：中文约 0.7 token/字，英文约 0.25 token/词。"""
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


SYSTEM = "你是一个客服助手。回答要准确，只用参考资料里的内容。"

HISTORY = [
    ("user", "你好"),
    ("assistant", "你好，请问有什么可以帮您？"),
    ("user", "我上周买的耳机有点问题"),
    ("assistant", "方便说一下具体什么问题吗？"),
    ("user", "左耳没声音"),
    ("assistant", "建议您先检查一下蓝牙配对。"),
    ("user", "试过了，还是不行"),
    ("assistant", "那可能是硬件问题，可以申请检测。"),
    ("user", "检测要多久"),
    ("assistant", "一般 3-5 个工作日。"),
    ("user", "太久了，我明天要出差"),
    ("assistant", "我们可以提供备用机。"),
]

RETRIEVAL = [
    "【售后政策 §2.1】签收后 7 天内，商品有质量问题可无理由退货。",
    "【售后政策 §2.3】超过 7 天但在 30 天内，需提供检测报告方可换货。",
    "【物流说明 §1.4】备用机需在 24 小时内归还，逾期按日租金 20 元计费。",
    "【补偿标准 §3.2】因商品质量问题导致的不便，可申请最高 50 元补偿。",
]

QUESTION = "我的耳机能退吗？"


def build_naive(history: list[tuple[str, str]], retrieval: list[str], question: str) -> str:
    """最常见的写法：全部拼起来。"""
    parts = [f"[system] {SYSTEM}"]
    parts += [f"[{r}] {c}" for r, c in history]
    parts += [f"[doc] {d}" for d in retrieval]
    parts.append(f"[user] 【参考资料】见上【问题】{question}")
    return "\n".join(parts)


def truncate_head(text: str, window: int) -> str:
    """按窗口硬截断（保留头部，砍掉尾部）。"""
    est = est_tokens(text)
    if est <= window:
        return text
    keep = int(len(text) * window / est)
    return text[:keep]


def main() -> None:
    full = build_naive(HISTORY, RETRIEVAL, QUESTION)
    window = 110

    print("=" * 74)
    print("第 1 级：把一切塞进去，然后截断")
    print("=" * 74)
    print(f"  完整上下文：{est_tokens(full)} token")
    print(f"  模型窗口  ：{window} token  ← 装不下")

    kept = truncate_head(full, window)
    print(f"\n  截断后：{est_tokens(kept)} token")

    print("\n  截断后模型实际看到的最后 5 行：")
    for line in kept.split("\n")[-5:]:
        print(f"    {line}")

    print("\n" + "=" * 74)
    print("问题在哪")
    print("=" * 74)
    print("  · 12 轮「你好 / 好的 / 试过了」的闲聊，全部保留了下来")
    print("  · 4 条售后政策 —— 一条都没进去（它们在上下文的最末尾）")
    print("  · 用户问「能退吗」，模型手上没有任何一条政策依据")
    print()
    print("  ⚠️ 这个 bug 不会报错。模型会流畅地编一个答案出来 ——")
    print("     而且编得还挺像真的，因为你给了它「客服助手」的人设。")
    print()
    print("  👉 下一级：不按「谁先来」分配空间，按「谁重要」分配预算。")


if __name__ == "__main__":
    main()
