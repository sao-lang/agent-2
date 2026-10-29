"""把分数校准成通过率，再用两个代价参数选出阈值。

输入是一批带标注的请求：每条有意图分数、以及"小模型答了会不会错"。
数据是脚本写死的，用来演示算法；真实系统要换成线上抽样。
"""

from __future__ import annotations

import random

# ---------------------------------------------------------------- 标注批次

# 分数 → 答对了吗。真实系统里这两列分别来自意图模型与人工抽检。
LABELED: list[tuple[float, bool]] = [
    (0.91, True), (0.88, True), (0.86, True), (0.85, True), (0.83, True),
    (0.82, True), (0.81, True), (0.80, True), (0.79, True), (0.78, True),
    (0.77, True), (0.76, False), (0.75, True), (0.74, True), (0.73, False),
    (0.72, True), (0.70, True), (0.68, True), (0.67, False), (0.65, True),
    (0.63, True), (0.61, False), (0.59, True), (0.57, False), (0.55, True),
    (0.52, False), (0.48, False), (0.45, True), (0.41, False), (0.38, False),
    (0.34, False), (0.30, False), (0.26, False), (0.22, False), (0.18, False),
    (0.15, False), (0.12, False), (0.09, False), (0.05, False), (0.02, False),
]

EDGES = [0.8, 0.6, 0.4]  # 桶的上界，从高到低


def bucket_table(labeled: list[tuple[float, bool]]) -> list[dict]:
    """按 EDGES 分桶，统计每桶的样本数与实际正确率。"""
    rows = []
    prev = 1.01
    for edge in EDGES:
        rows.append({"range": (edge, prev), "n": 0, "ok": 0})
        prev = edge
    rows.append({"range": (0.0, prev), "n": 0, "ok": 0})

    for score, correct in labeled:
        for row in rows:
            lo, hi = row["range"]
            if lo <= score < hi:
                row["n"] += 1
                row["ok"] += int(correct)
                break

    for row in rows:
        lo, hi = row["range"]
        row["p"] = row["ok"] / row["n"] if row["n"] else 0.0
        row["label"] = f"{lo:.1f}-{hi:.1f}" if hi <= 1.0 else f"≥{lo:.1f}"
    return rows


def expected_cost(rows: list[dict], t: float,
                  c_escalate: float, c_wrong: float) -> dict:
    """阈值 t 的期望成本：低于 t 的升级，高于等于 t 的放行、错答付 c_wrong。"""
    escalated = sum(r["n"] for r in rows if r["range"][0] < t)
    wrong = sum(r["n"] * (1 - r["p"]) for r in rows if r["range"][0] >= t)
    return {"t": t, "escalated": escalated, "wrong": round(wrong, 1),
            "cost": round(escalated * c_escalate + wrong * c_wrong, 1)}


if __name__ == "__main__":
    rows = bucket_table(LABELED)

    print("=== 1. 按分数分桶，统计实际正确率 ===")
    print(f"  {'分数桶':<10}{'样本数':>6}{'答对':>6}{'正确率':>8}")
    for r in rows:
        print(f"  {r['label']:<10}{r['n']:>6}{r['ok']:>6}{r['p']:>8.0%}")
    total_wrong = sum(1 for _, c in LABELED if not c)
    print(f"  合计 {len(LABELED)} 条，错答 {total_wrong} 条"
          f"（{total_wrong / len(LABELED):.0%}）")

    print()
    print("=== 2. 两个代价参数下，阈值怎么选 ===")
    for c_wrong, tag in [(6.0, "对外客服，答错代价高"), (1.0, "内部工具，答错只是多问一次")]:
        best = None
        print(f"  -- {tag}：c_escalate=1, c_wrong={c_wrong:g}")
        for t in [0.4, 0.6, 0.8]:
            e = expected_cost(rows, t, 1.0, c_wrong)
            mark = ""
            if best is None or e["cost"] < best["cost"]:
                best = e
            print(f"     阈值 {t:.1f}  升级 {e['escalated']:>2} 条  "
                  f"期望错答 {e['wrong']:>5}  期望成本 {e['cost']:>6}")
        print(f"     最优阈值 {best['t']:.1f}，期望成本 {best['cost']}")

    print()
    print("=== 3. 分数不是概率：同一分数在不同批次上的正确率 ===")
    rng = random.Random(7)
    batch_a = [(0.8, rng.random() < 0.96) for _ in range(200)]
    batch_b = [(0.8, rng.random() < 0.55) for _ in range(200)]
    accs = []
    for name, batch in [("开发期自编问题", batch_a), ("上线后真实流量", batch_b)]:
        acc = sum(1 for _, c in batch if c) / len(batch)
        accs.append(acc)
        print(f"  {name:<14} 分数 0.8 的样本 200 条，实际正确率 {acc:.0%}")
    print(f"  同一个分数，两批数据上的正确率差 {round(abs(accs[0] - accs[1]) * 100)} "
          "个百分点：分数要校准才能当概率用")
