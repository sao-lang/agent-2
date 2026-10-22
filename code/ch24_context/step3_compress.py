"""第 24 章 · 第 3 级：历史太长了怎么办 —— 四种压缩法，用数字选。

运行：
    python code/ch24_context/step3_compress.py

新增的一个概念：**压缩不是"删掉一部分"，是"决定保留哪些事实"。**

预算只能决定"历史最多占多少"，但历史本身可能还是太长。
这一级用 22 轮对话 + 5 个埋在前面的关键事实，测四种压缩法各丢了多少。

关键指标不是"压缩到多少 token"，而是**"关键事实还在不在"**。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 测试数据

# 5 个埋在前面的关键事实（后面会检查它们是否幸存）
KEY_FACTS = ["张伟", "物流", "杭州", "A12345", "500 元"]

HISTORY: list[dict[str, str]] = [
    {"role": "user", "content": "我叫张伟，我手机号是 138xxxx"},
    {"role": "assistant", "content": "好的张先生，已记录。"},
    {"role": "user", "content": "我上次那个订单 A12345 的物流怎么不动了"},
    {"role": "assistant", "content": "我查一下物流状态。"},
    {"role": "assistant", "content": "显示在杭州转运中心。"},
    {"role": "user", "content": "我预算最多 500 元，别超"},
    {"role": "assistant", "content": "明白，会控制在 500 元内。"},
    {"role": "user", "content": "那个屏幕有点亮"},
    {"role": "assistant", "content": "可以调亮度。"},
    {"role": "user", "content": "调过了"},
    {"role": "assistant", "content": "那是屏幕本身的问题。"},
    {"role": "user", "content": "好吧"},
    {"role": "assistant", "content": "需要我帮您申请检测吗？"},
    {"role": "user", "content": "先不用"},
    {"role": "assistant", "content": "好的，有需要随时找我。"},
    {"role": "user", "content": "嗯"},
    {"role": "assistant", "content": "还有什么问题吗？"},
    {"role": "user", "content": "暂时没有"},
    {"role": "assistant", "content": "祝您生活愉快。"},
    {"role": "user", "content": "对了，能开个发票吗"},
    {"role": "assistant", "content": "可以，请提供抬头。"},
    {"role": "user", "content": "那我想退了"},
]

FACT_MARKERS = ("我叫", "我的", "记住", "偏好", "不要", "必须", "禁止", "账号", "地址", "金额", "订单", "预算")


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


def is_fact(msg: dict[str, str]) -> bool:
    return msg["role"] == "user" and any(k in msg["content"] for k in FACT_MARKERS)


def fake_summarize(msgs: list[dict[str, str]]) -> str:
    """假摘要器：真实系统里这是一次模型调用。

    这里刻意保留**部分**早期事实、丢掉细节 —— 这正是真实摘要器的典型行为：
    它记得"用户说过预算"，但记不住"500 元"这个数字。
    """
    text = " ".join(m["content"] for m in msgs)
    kept = [f for f in ("张伟", "订单", "物流", "预算") if f in text]
    return f"用户此前聊了 {len(msgs)} 轮，提到过：{'、'.join(kept) or '一些日常问题'}。"


# ---------------------------------------------------------------- 四种压缩法

def compress_sliding(budget: int) -> list[dict[str, str]]:
    """滑窗：只留最近的。"""
    kept, total = [], 0
    for m in reversed(HISTORY):
        t = est_tokens(m["content"])
        if total + t > budget:
            break
        kept.append(m)
        total += t
    return list(reversed(kept))


def compress_summary(budget: int, keep_recent: int = 2) -> list[dict[str, str]]:
    """摘要：早期压成一段话。"""
    recent = HISTORY[-keep_recent:]
    early = HISTORY[:-keep_recent]
    summary = fake_summarize(early)
    while est_tokens(summary) > budget * 0.5 and len(summary) > 20:
        summary = summary[: len(summary) // 2]
    return [{"role": "system", "content": f"【早期摘要】{summary}"}] + recent


def compress_selective(budget: int) -> list[dict[str, str]]:
    """选择性保留：事实全留，其余按最近优先塞。"""
    facts = [m for m in HISTORY if is_fact(m)]
    rest = [m for m in HISTORY if not is_fact(m)]
    kept, total = list(facts), sum(est_tokens(m["content"]) for m in facts)
    for m in reversed(rest):
        t = est_tokens(m["content"])
        if total + t > budget:
            break
        kept.append(m)
        total += t
    order = {id(m): i for i, m in enumerate(HISTORY)}
    return sorted(kept, key=lambda m: order[id(m)])


def compress_hybrid(budget: int) -> list[dict[str, str]]:
    """混合：事实全留 + 其余摘要。**生产默认**。"""
    facts = [m for m in HISTORY if is_fact(m)]
    others = [m for m in HISTORY if not is_fact(m)]
    imp = sum(est_tokens(m["content"]) for m in facts)
    remain = max(budget - imp, budget // 3)
    summary = fake_summarize(others)
    while est_tokens(summary) > remain and len(summary) > 20:
        summary = summary[: len(summary) // 2]
    out = [{"role": "system", "content": f"【其余对话摘要】{summary}"}]
    return out + facts


# ---------------------------------------------------------------- 评测

@dataclass
class Result:
    name: str
    kept: int
    tokens: int
    facts_kept: list[str]
    lost: list[str]

    @property
    def rate(self) -> float:
        return len(self.facts_kept) / len(KEY_FACTS)

    @property
    def per_1k(self) -> float:
        """每 1,000 token 保住了几个事实 —— 这才是"压缩效率"的正确口径。"""
        return len(self.facts_kept) / max(self.tokens, 1) * 1000


def evaluate(name: str, msgs: list[dict[str, str]]) -> Result:
    text = "\n".join(m["content"] for m in msgs)
    kept = [f for f in KEY_FACTS if f in text]
    return Result(
        name=name,
        kept=len(msgs),
        tokens=sum(est_tokens(m["content"]) for m in msgs),
        facts_kept=kept,
        lost=[f for f in KEY_FACTS if f not in kept],
    )


def main() -> None:
    budget = 60
    print("=" * 78)
    print("第 3 级：四种压缩法，同一个预算下谁保住了关键事实")
    print("=" * 78)
    print(f"  预算：{budget} token    关键事实：{KEY_FACTS}")

    results = [
        evaluate("不压缩", HISTORY),
        evaluate("滑窗", compress_sliding(budget)),
        evaluate("摘要", compress_summary(budget)),
        evaluate("选择性保留", compress_selective(budget)),
        evaluate("混合（事实+摘要）", compress_hybrid(budget)),
    ]

    print(f"\n{'策略':<20}{'保留条数':>8}{'token':>8}{'事实保留率':>12}{'每千token事实':>14}   丢失的事实")
    print("-" * 92)
    for r in results:
        lost = ", ".join(r.lost) if r.lost else "—"
        print(f"{r.name:<20}{r.kept:>8}{r.tokens:>8}{r.rate:>11.0%}{r.per_1k:>14.1f}   {lost}")

    print("\n" + "=" * 78)
    print("四种方法的本质差异")
    print("=" * 78)
    print("  · 滑窗      ：最省 token，但**早期事实全丢** —— 张伟、订单号、预算都没了")
    print("  · 摘要      ：保住了部分，但细节被抹平（'500 元'这种数字最容易丢）")
    print("  · 选择性保留 ：事实全留，但需要 is_fact 判定器；其余内容直接扔")
    print("  · 混合      ：事实全留 + 其余压成摘要 —— 兼顾保真和上下文完整")
    print()
    print("  👉 没有「最好的压缩法」，只有「你的场景里哪类信息不能丢」。")
    print("     动手之前先写清楚：哪 3 件事丢了会让用户投诉？那就是 is_fact 的规则。")


if __name__ == "__main__":
    main()
