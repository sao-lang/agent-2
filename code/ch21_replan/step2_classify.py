"""第 21 章 · 第 2 级：按错误类型分级处理（不是所有失败都该"重来"）。

运行：
    python code/ch21_replan/step2_classify.py

新增的一个概念：**错误分级（failure triage）**。

新手最常见的做法是"一失败就全部重来"，成本翻三倍还更慢。
正确做法是先按**错误信息**判断它属于哪一类：

  · 瞬时故障（超时、503、429）  → 重试就好，计划不用改
  · 局部错误（参数、工具名）    → 只换那一步
  · 前提错误（数据源搞错了）    → 只能全部重来

判断依据是**错误信息**，不是"模型觉得".
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 分级表

# 关键词 → 分类。生产里这张表应该放配置文件，方便运维加规则。
TRIAGE = {
    "transient": ("timeout", "timed out", "503", "502", "429", "connection reset", "temporarily"),
    "local": ("参数", "invalid", "未知动作", "not found", "unknown action", "valueerror"),
    "fatal": ("schema mismatch", "数据源", "permission denied", "unauthorized"),
}


def classify(error: str) -> str:
    err = (error or "").lower()
    for kind, words in TRIAGE.items():
        if any(w in err for w in words):
            return kind
    return "local"          # 默认按局部处理：保守但便宜


def decide(error: str, attempts: int, max_retries: int = 2, budget_left: int = 2) -> str:
    """返回 retry / patch / replan_all / give_up。"""
    if budget_left <= 0:
        return "give_up"
    kind = classify(error)
    if kind == "transient":
        return "retry" if attempts < max_retries else "patch"
    if kind == "fatal":
        return "replan_all"
    return "patch"


# ---------------------------------------------------------------- 演示

@dataclass
class Case:
    error: str
    attempts: int
    note: str


def main() -> None:
    print("=" * 78)
    print("第 2 级：同一个失败，不同分类 → 不同决策")
    print("=" * 78)

    cases = [
        Case("TimeoutError: 上游 30s 未响应", 1, "第一次超时 → 值得再试一次"),
        Case("TimeoutError: 上游 30s 未响应", 3, "第三次还超时 → 重试没意义，换工具"),
        Case("未知动作：search_B", 1, "工具名写错 → 重试 100 次也一样"),
        Case("ValueError: 参数 q 不能为空", 1, "参数错误 → 只改参数就够"),
        Case("schema mismatch: 源表结构已变更", 1, "前提变了 → 已完成的结果都不可信"),
        Case("HTTP 429 Too Many Requests", 1, "限流 → 等一下再来"),
    ]

    print(f"\n{'错误（截断）':<36}{'已试':>4}{'分类':>10}{'决策':>12}  说明")
    print("-" * 78)
    for c in cases:
        kind = classify(c.error)
        action = decide(c.error, c.attempts)
        print(f"{c.error[:34]:<36}{c.attempts:>4}{kind:>10}{action:>12}  {c.note}")

    print("\n" + "=" * 78)
    print("为什么必须分级")
    print("=" * 78)
    print("  · 对「超时」用 replan_all → 前面查到的结果全扔，白花 3 倍钱")
    print("  · 对「工具名写错」用 retry  → 试 10 次还是同样的错，纯浪费")
    print("  · 对「数据源搞错」用 patch  → 修补出来的计划建立在错误前提上")
    print()
    print("  👉 分级表的每一行，都对应一次真实的成本差异。")
    print("     所以这张表应该能被运维改，而不是写死在 if-else 里。")

    print("\n" + "=" * 78)
    print("两个必须加的护栏")
    print("=" * 78)
    print("  1. 单步重试上限（max_retries）：防止对一个必然失败的动作狂试")
    print("  2. 全局重规划预算（replan_budget）：防止「重规划 → 又失败 → 再重规划」")
    print()
    print("  第 2 条尤其重要：没有它，重规划会变成第 16 章的无限循环。")
    print("  实测：把 replan_budget 设成 10**9，一个「每次修复都产生新错误」的修复器")
    print("        会让程序和钱包同时失控。")


if __name__ == "__main__":
    main()
