"""第 24 章 · 第 2 级：按"用途"分预算，而不是按"谁先来"。

运行：
    python code/ch24_context/step2_budget.py

新增的一个概念：**预算槽位（budget slots）**。

把窗口切成四份，每份只给自己的用途用：
    system  10%   角色与规则，不能砍
    history 30%   之前说过什么，可以砍
    retrieval 45% 检索到的事实，**最重要**
    output  15%   留给模型生成，不能算进输入

为什么必须固定比例？
  因为"按需分配"时，历史会无限膨胀，把检索结果挤出去 ——
  而历史对答案的贡献通常**最低**。
"""
from __future__ import annotations

from dataclasses import dataclass

from step1_overflow import HISTORY, QUESTION, RETRIEVAL, SYSTEM, est_tokens


@dataclass
class ContextBudget:
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
        lines = [f"{'槽位':<16}{'预算':>7}{'实际':>7}{'使用率':>8}"]
        lines.append("-" * 40)
        for k, cap in self.slots().items():
            used = actual.get(k, 0)
            flag = "  ⚠️ 超了" if used > cap else ""
            lines.append(f"{k:<16}{cap:>7}{used:>7}{used / cap if cap else 0:>7.0%}{flag}")
        return "\n".join(lines)


def build_with_budget(
    budget: ContextBudget,
    history: list[tuple[str, str]],
    retrieval: list[str],
    question: str,
) -> tuple[list[str], dict[str, int]]:
    slots = budget.slots()

    # ① 检索：按顺序（调用方已按相关性排序）尽量塞
    kept_docs, used_r = [], 0
    for doc in retrieval:
        t = est_tokens(doc)
        if used_r + t > slots["retrieval"]:
            break
        kept_docs.append(doc)
        used_r += t

    # ② 历史：从最近往前塞，但**不许超过自己的槽位**
    kept_hist, used_h = [], 0
    for role, content in reversed(history):
        line = f"[{role}] {content}"
        t = est_tokens(line)
        if used_h + t > slots["history"]:
            break
        kept_hist.insert(0, line)
        used_h += t

    # ③ 组装顺序：system 最前，问题最后（避免 lost in the middle）
    #    注意：问题本身也要占检索槽 —— 否则"预算"和"实际"对不上
    q_tokens = est_tokens(question)
    if used_r + q_tokens > slots["retrieval"] and kept_docs:
        kept_docs.pop()
        used_r -= est_tokens(kept_docs[-1]) if kept_docs else 0
    msgs = [
        f"[system] {SYSTEM}",
        *kept_hist,
        "[user] 【参考资料】\n" + "\n".join(kept_docs) + f"\n\n【问题】{question}",
    ]

    actual = {
        "system": est_tokens(SYSTEM),
        "history": used_h,
        "retrieval": used_r + q_tokens,
        "output_reserve": 0,
    }
    return msgs, actual


def main() -> None:
    print("=" * 74)
    print("第 2 级：按用途分预算")
    print("=" * 74)

    # 窗口调小，才能看出"分配"和"截断"的差别
    # total=300 → history 只有 90 token（约 4 轮），retrieval 有 135（约 2 条政策）
    budget = ContextBudget(total=300)
    msgs, actual = build_with_budget(budget, HISTORY, RETRIEVAL, QUESTION)

    print("\n【槽位使用情况】")
    print(budget.report(actual))

    print(f"\n【模型实际收到 {est_tokens(chr(10).join(msgs))} token】")
    for m in msgs:
        head = m.split("\n")[0]
        print(f"  {head[:70]}{'…' if len(head) > 70 else ''}")

    print("\n" + "=" * 74)
    print("和上一级比，差别在哪")
    print("=" * 74)
    print("  第 1 级：检索结果全被截掉，历史全部保留 → 模型没有依据")
    print("  第 2 级：检索留住了 2 条政策，历史只留最近 4 轮 → 模型有依据")
    print()
    print("  👉 关键不是「比例是多少」，而是**你先声明了谁重要**。")
    print("     比例可以调，但没有比例就只剩「谁先来谁占坑」。")

    print("\n" + "=" * 74)
    print("两条经验规则")
    print("=" * 74)
    print("  · 检索至少 40%：低于这个数，RAG 基本没起作用")
    print("  · 输出预留至少 15%：不留的话，长回答会在中途被 max_tokens 截断")


if __name__ == "__main__":
    main()
