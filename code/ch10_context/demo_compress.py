"""第 10 章示例 2：历史压缩三法 + 混合法，用"事实保留率"量化对比（不需要 API）。

运行：
    python code/ch10_context/demo_compress.py

这是本章的核心实验：
同一段 20 轮对话，用四种策略压缩到同样的 token 预算，
然后检查"第 2 轮说过的事实还能不能找到"。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import (  # noqa: E402
    compress_hybrid,
    compress_selective,
    compress_sliding,
    compress_summary,
    est_tokens,
    is_fact,
)


def build_history() -> list[dict]:
    """20 轮对话，前几轮埋了 5 个关键事实。"""
    h = [
        {"role": "user", "content": "我叫张伟，是做物流的，在杭州。"},
        {"role": "assistant", "content": "你好张伟，很高兴认识你。"},
        {"role": "user", "content": "我有个订单 A12345，上周买的蓝牙耳机。"},
        {"role": "assistant", "content": "好的，我记下了订单号 A12345。"},
        {"role": "user", "content": "我的预算是 500 元以内，不要太贵。"},
        {"role": "assistant", "content": "明白，500 元以内的方案。"},
    ]
    # 中间填充 14 轮闲聊（模拟真实对话里的噪音）
    for i in range(7):
        h.append({"role": "user", "content": f"顺便问下，你们最近有什么活动吗（第{i}次问）？"})
        h.append({"role": "assistant", "content": "有的，本月满 300 减 30，会员还额外 9 折。"})
    h.extend([
        {"role": "user", "content": "那右耳的滋滋声怎么办？"},
        {"role": "assistant", "content": "建议先换设备测试，仍有问题走售后。"},
    ])
    return h


FACTS = ["张伟", "物流", "杭州", "A12345", "500 元"]


def summarize_without_llm(msgs: list[dict]) -> str:
    """用一个"假摘要器"代替模型：只保留前 30 个字。

    为什么不用真模型？为了让实验可复现——真模型每次摘要可能不同，
    你就无法判断"差异是压缩策略导致的还是模型抖动导致的"。
    """
    text = " ".join(m["content"] for m in msgs)
    return text[:60] + "……（摘要）"


def measure(kept: list[dict]) -> tuple[int, list[str], str]:
    joined = " ".join(m["content"] for m in kept)
    tokens = est_tokens(joined)
    found = [f for f in FACTS if f in joined]
    return tokens, found, "".join(kept[-1]["content"][:30])


def main() -> None:
    history = build_history()
    budget = 150  # 很小的预算，逼近真实压缩场景（必须小于原始总量，否则测不出差异）

    strategies = {
        "不压缩": lambda h: h,
        "滑窗": lambda h: compress_sliding(h, budget),
        "摘要": lambda h: compress_summary(h, budget, summarize_without_llm),
        "选择性保留": lambda h: compress_selective(h, budget, is_fact),
        "混合（重要+摘要）": lambda h: compress_hybrid(h, budget, summarize_without_llm, is_fact),
    }

    print(f"原始对话：{len(history)} 条，{est_tokens(' '.join(m['content'] for m in history))} token")
    print(f"压缩预算：{budget} token    关键事实：{FACTS}\n")

    rows = []
    for name, fn in strategies.items():
        kept = fn(history)
        tokens, found, _ = measure(kept)
        rows.append((name, len(kept), tokens, found))

    print(f"{'策略':<18}{'保留条数':>8}{'token':>8}{'事实保留率':>12}   丢失的事实")
    print("-" * 78)
    for name, n, tokens, found in rows:
        rate = len(found) / len(FACTS)
        lost = [f for f in FACTS if f not in found]
        print(f"{name:<18}{n:>8}{tokens:>8}{rate:>11.0%}   {', '.join(lost) if lost else '—'}")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  · 滑窗     ：token 最少，但**早期事实全丢**（张伟、订单号都没了）")
    print("  · 摘要     ：保住了部分，但细节被抹平，且要多花一次模型调用")
    print("  · 选择性保留：事实保留率最高，但需要 is_fact 判定器")
    print("  · 混合     ：兼顾——事实全留，其余压成摘要")
    print("\n  👉 没有「最好的压缩方法」，只有「你的场景里哪类信息不能丢」。")
    print("     先定义「不能丢的东西」，再选策略——这是上下文工程的第一步。")


if __name__ == "__main__":
    main()
