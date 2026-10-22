"""第 2 章 step1：一段话到底要花多少 token（离线，不需要 API key）。

运行：
    python code/ch02_token/step1_count_tokens.py

上一级的痛点（第 1 章）：知道模型按 token 算，但不知道自己的中文到底占多少 token。
                         于是"我给了它十万字文档"这种说法完全没法用——
                         十万字可能是 7 万 token，也可能是 15 万 token。

这一级做什么：给你**三个口径**，并让它们的差距可见。

  ① 字数口径   len(text)                      —— 你直觉会用的
  ② 汉字口径   汉字 × 0.7 + 其余 / 4          —— 本书全书统一的估算（common/context.py）
  ③ 字节口径   UTF-8 字节数 / 3               —— 悲观上限，用来留安全余量

为什么给三个而不是一个？
因为真实的 token 数只有厂商的分词器知道，**你手上永远只有估算。**
工程上的正确做法是在这三个值里取**最大值**做预算，而不是取平均值。

要看的三件事：
  1. 中文的 token 数 ≈ 字数 × 0.6~1.0，绝不是"1 字 = 1 token"
  2. 中英混排时字数口径会严重低估（英文 4 字符才算 1 token）
  3. 同一段话，三种口径能差出 2 倍 → 所以预算必须留余量
"""
from __future__ import annotations

import json

# ---- 三个口径 --------------------------------------------------------------


def count_chars(text: str) -> int:
    """直觉口径：一个字符算一个。"""
    return len(text)


def count_cjk_aware(text: str) -> int:
    """本书全书统一口径：汉字算 0.7 个 token，其余算 1/4 个 token。

    系数 0.7 来自主流中文分词器（Qwen / DeepSeek / GLM）的实测均值：
    常见汉字多数被切成 1 个 token，但高频词会被合并成 1 个 token 覆盖 2~3 个字。
    """
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


def count_bytes(text: str) -> int:
    """悲观口径：UTF-8 字节数 / 3。用来算"最坏情况要多少"。"""
    return len(text.encode("utf-8")) // 3 + 1


def budget_of(text: str) -> int:
    """工程上用最大值做预算——低估会截断，高估只是浪费一点空间。"""
    return max(count_chars(text), count_cjk_aware(text), count_bytes(text))


# ---- 六个典型样本 ----------------------------------------------------------

SAMPLES: list[tuple[str, str]] = [
    ("纯中文短句", "退款要 7 天。"),
    ("纯中文长段", "签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。"),
    ("纯英文短句", "The refund takes 7 days."),
    ("纯英文长段", "Items may be returned within 7 days of delivery if unopened and resalable."),
    ("中英混排", "退款周期 refund period 是 7 天，超过 7 days 需要人工审核（manual review）。"),
    ("代码 / JSON", '{"order_id": "A12345", "status": "refund_pending", "amount": 299.0}'),
]


def main() -> None:
    print("=" * 90)
    print("一段话到底要花多少 token：三种口径对比")
    print("=" * 90)

    header = f"{'样本':<12}{'字数':>7}{'汉字口径':>10}{'字节口径':>10}{'预算(取最大)':>13}   汉字占比"
    print(header)
    print("-" * 90)

    for name, text in SAMPLES:
        cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        print(
            f"{name:<12}{count_chars(text):>7}{count_cjk_aware(text):>10}"
            f"{count_bytes(text):>10}{budget_of(text):>13}   {cn / len(text):>6.0%}"
        )

    print("-" * 90)

    print("\n" + "=" * 90)
    print("口径差异有多大（以汉字口径为基准）")
    print("=" * 90)
    print(f"{'样本':<12}{'字数口径/汉字口径':>20}{'字节口径/汉字口径':>20}")
    print("-" * 90)
    for name, text in SAMPLES:
        base = count_cjk_aware(text)
        print(f"{name:<12}{count_chars(text) / base:>19.2f}x{count_bytes(text) / base:>19.2f}x")

    print("-" * 90)

    long_cn = SAMPLES[1][1] * 20
    print(f"\n把「纯中文长段」复制 20 遍，得到 {len(long_cn)} 字：")
    print(f"  字数口径  {count_chars(long_cn):>8,} token")
    print(f"  汉字口径  {count_cjk_aware(long_cn):>8,} token")
    print(f"  字节口径  {count_bytes(long_cn):>8,} token")
    print(f"  → 两个极端相差 {count_bytes(long_cn) / count_cjk_aware(long_cn):.2f} 倍")

    print("\n" + "=" * 90)
    print("同一段话，塞进不同窗口能装几份")
    print("=" * 90)
    windows = [("小模型 8K", 8_000), ("主流 32K", 32_000), ("长上下文 128K", 128_000), ("超长 1M", 1_000_000)]
    est = count_cjk_aware(long_cn)
    print(f"{'窗口':<16}{'容量(token)':>14}{'能装几份':>10}   {'说明'}")
    print("-" * 90)
    for label, cap in windows:
        copies = cap // est
        note = "装不下 1 份" if copies == 0 else f"约 {copies} 份"
        print(f"{label:<16}{cap:>14,}{copies:>10}   {note}")

    print("-" * 90)

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · 中文 1 字 ≈ 0.7 token 是**估算**，不是承诺。真实值只有分词器知道。")
    print("  · 字数口径在纯中文下还算靠谱，一中英混排就崩——英文要 4 个字符才算 1 token。")
    print("  · 所以做预算时取**最大值**，而不是平均值：")
    print("      低估 → 请求被截断 / 抛 400")
    print("      高估 → 只是少塞几条无关内容，代价几乎为零")
    print()
    print("  下一步（step2）：把 token 换算成钱。token 数是过程，钱才是决策依据。")

    # 供测试断言：保证口径顺序是稳定的
    probe = json.dumps({"chars": count_chars(long_cn), "cjk": count_cjk_aware(long_cn)}, ensure_ascii=False)
    assert count_cjk_aware(long_cn) < count_chars(long_cn), probe


if __name__ == "__main__":
    main()
