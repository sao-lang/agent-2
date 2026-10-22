"""第 43 章产出：上下文预算分配器 + 历史压缩三法。

核心洞察：Context 是一个**有预算的资源**，不是"能塞多少塞多少"。
把预算可视化之后，你才会发现自己一直在用 70% 的空间装没用的历史。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


# ============================================================ 预算分配

@dataclass
class ContextBudget:
    """按用途切分 token 预算。

    为什么固定分配而不是"按需"？
    因为按需时，历史会无限制膨胀并挤掉检索结果——
    而检索结果往往比历史更重要（你只需要知道用户问什么，不需要知道上个月聊了什么）。
    """

    total: int = 8000
    system_ratio: float = 0.10
    history_ratio: float = 0.30
    retrieval_ratio: float = 0.45
    output_reserve_ratio: float = 0.15

    def slots(self) -> dict[str, int]:
        return {
            "system": int(self.total * self.system_ratio),
            "history": int(self.total * self.history_ratio),
            "retrieval": int(self.total * self.retrieval_ratio),
            "output_reserve": int(self.total * self.output_reserve_ratio),
        }

    def report(self, actual: dict[str, int]) -> str:
        s = self.slots()
        lines = [f"{'槽位':<14}{'预算':>8}{'实际':>8}{'使用率':>8}"]
        lines.append("-" * 40)
        for k, v in s.items():
            used = actual.get(k, 0)
            rate = used / v if v else 0
            flag = " ⚠️" if rate > 1 else ""
            lines.append(f"{k:<14}{v:>8}{used:>8}{rate:>7.0%}{flag}")
        return "\n".join(lines)


# ============================================================ 历史压缩三法

def compress_sliding(
    history: list[dict[str, Any]], budget: int, est: Callable[[str], int] = est_tokens
) -> list[dict[str, Any]]:
    """滑窗：保留最近 N 条。

    优点：保真、简单
    缺点：早期事实直接丢失
    """
    kept, total = [], 0
    for m in reversed(history):
        t = est(m.get("content", ""))
        if total + t > budget:
            break
        kept.append(m)
        total += t
    return list(reversed(kept))


def compress_summary(
    history: list[dict[str, Any]],
    budget: int,
    summarize: Callable[[list[dict]], str],
    keep_recent: int = 2,
    est: Callable[[str], int] = est_tokens,
) -> list[dict[str, Any]]:
    """摘要：把早期内容压成一段摘要。

    优点：能保留早期信息（虽然失真）
    缺点：摘要本身要花一次模型调用，且会丢细节
    """
    if not history:
        return []
    recent = history[-keep_recent:]
    earlier = history[:-keep_recent]
    if not earlier:
        return recent

    summary = summarize(earlier)
    # 摘要如果还是超预算，就硬截断
    while est(summary) > budget * 0.5 and len(summary) > 50:
        summary = summary[: len(summary) // 2]

    return [{"role": "system", "content": f"【早期对话摘要】{summary}"}] + recent


def compress_selective(
    history: list[dict[str, Any]],
    budget: int,
    is_important: Callable[[dict], bool],
    est: Callable[[str], int] = est_tokens,
) -> list[dict[str, Any]]:
    """选择性保留：重要的全留，不重要的丢。

    这是三种里最实用的——因为对话里"事实"只占少数几句话。
    关键是要有一个 is_important 判定（见下面的实现）。
    """
    important = [m for m in history if is_important(m)]
    rest = [m for m in history if not is_important(m)]

    kept, total = [], 0
    for m in important:
        t = est(m.get("content", ""))
        if total + t <= budget:
            kept.append(m)
            total += t

    # 剩余预算给最近的普通消息
    for m in reversed(rest):
        t = est(m.get("content", ""))
        if total + t > budget:
            break
        kept.append(m)
        total += t

    # 保持原顺序
    order = {id(m): i for i, m in enumerate(history)}
    return sorted(kept, key=lambda m: order.get(id(m), 0))


def compress_hybrid(
    history: list[dict[str, Any]],
    budget: int,
    summarize: Callable[[list[dict]], str],
    is_important: Callable[[dict], bool],
    est: Callable[[str], int] = est_tokens,
) -> list[dict[str, Any]]:
    """混合：重要事实全留 + 其余摘要。

    第 40 章会用它做短期记忆的默认实现。
    """
    important = [m for m in history if is_important(m)]
    others = [m for m in history if not is_important(m)]

    imp_tokens = sum(est(m.get("content", "")) for m in important)
    remain = max(budget - imp_tokens, budget // 3)

    summary = summarize(others) if others else ""
    while est(summary) > remain and len(summary) > 40:
        summary = summary[: len(summary) // 2]

    out: list[dict[str, Any]] = []
    if summary:
        out.append({"role": "system", "content": f"【其余对话摘要】{summary}"})
    out.extend(important)
    return out


# ============================================================ 重要性判定

FACT_MARKERS = ("我叫", "我的", "记住", "偏好", "不要", "必须", "禁止", "账号", "地址", "金额", "订单")


def is_fact(msg: dict[str, Any]) -> bool:
    """判定一条消息是否包含"事实"。

    真实系统里这里会用小模型或用 LLM 标注（第 57 章的长期记忆抽取）。
    这里先用关键词，够做实验。
    """
    if msg.get("role") != "user":
        return False
    content = msg.get("content", "")
    return any(k in content for k in FACT_MARKERS)


# ============================================================ 组装

@dataclass
class ContextAssembler:
    """把四个来源拼成最终 prompt，并报告每个槽位的占用。"""

    budget: ContextBudget = field(default_factory=ContextBudget)

    def build(
        self,
        system: str,
        question: str,
        history: list[dict[str, Any]],
        retrieval: list[str],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        slots = self.budget.slots()

        # 检索结果：按预算裁剪（高分优先，调用方应已排序）
        kept_retrieval, used = [], 0
        for doc in retrieval:
            t = est_tokens(doc)
            if used + t > slots["retrieval"]:
                break
            kept_retrieval.append(doc)
            used += t

        # 历史：超出预算时按"最近优先"裁剪
        hist_used, kept_hist = 0, []
        for m in reversed(history):
            t = est_tokens(m.get("content", ""))
            if hist_used + t > slots["history"]:
                break
            kept_hist.append(m)
            hist_used += t
        kept_hist.reverse()

        messages = [
            {"role": "system", "content": system[: slots["system"]]},
            *kept_hist,
            {
                "role": "user",
                "content": "【参考资料】\n" + "\n---\n".join(kept_retrieval) + f"\n\n【问题】{question}",
            },
        ]

        actual = {
            "system": est_tokens(system[: slots["system"]]),
            "history": hist_used,
            "retrieval": used + est_tokens(question),
            "output_reserve": 0,
        }
        return messages, actual
