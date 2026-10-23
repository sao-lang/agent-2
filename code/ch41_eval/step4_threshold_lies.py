"""第 40 章 step4：同一批数据，换个阈值，结论就反了（离线）。

运行：
    python code/ch41_eval/step4_threshold_lies.py

上一级的痛点：报表告诉你"成本 -62%、质量 -25%"，但没人说得出"这算不算能上线"。

这一级做什么：把"判断"和"测量"分开。
  · 测量：通过率、成本、P95 延迟 —— 客观，能复现
  · 判断：门禁阈值 —— 是人的决定，必须写下来、被评审

本文件用同一份数据，演示三套阈值给出三种完全不同的上线结论。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 三套"看似都合理"的门禁（来自真实的团队分歧）
GATES: dict[str, dict[str, tuple[str, float]]] = {
    "质量优先（法务/医疗）": {
        "pass_rate": (">=", 0.98),
        "avg_cost": ("<=", 0.0100),
        "p95_latency_ms": ("<=", 3000),
    },
    "成本优先（内部工具）": {
        "pass_rate": (">=", 0.75),
        "avg_cost": ("<=", 0.0040),
        "p95_latency_ms": ("<=", 6000),
    },
    "体验优先（面向 C 端）": {
        "pass_rate": (">=", 0.90),
        "avg_cost": ("<=", 0.0080),
        "p95_latency_ms": ("<=", 1500),
    },
}

# 三份候选方案（数字来自 step3 的实验）
CANDIDATES: dict[str, dict[str, float]] = {
    "甲 便宜模型": {"pass_rate": 0.75, "avg_cost": 0.0030, "p95_latency_ms": 1200},
    "乙 精简 prompt": {"pass_rate": 1.00, "avg_cost": 0.0056, "p95_latency_ms": 1200},
    "丙 两者都改": {"pass_rate": 1.00, "avg_cost": 0.0024, "p95_latency_ms": 1200},
}


@dataclass
class Verdict:
    passed: bool
    failed: list[str]


def judge(metrics: dict[str, float], gate: dict[str, tuple[str, float]]) -> Verdict:
    failed = []
    for key, (op, limit) in gate.items():
        v = metrics[key]
        ok = v >= limit if op == ">=" else v <= limit
        if not ok:
            failed.append(f"{key}={v:.4g} 不满足 {op}{limit:.4g}")
    return Verdict(passed=not failed, failed=failed)


def main() -> None:
    print("=" * 88)
    print("同一份数字，三套门禁，三种结论")
    print("=" * 88)
    print(f"{'':<16}" + "".join(f"{g:<26}" for g in GATES))
    print("-" * 88)
    for name, m in CANDIDATES.items():
        cells = []
        for gate in GATES.values():
            v = judge(m, gate)
            cells.append(f"{'✅ 放行' if v.passed else '❌ 拦截':<26}")
        print(f"{name:<16}" + "".join(cells))

    print("\n各方案的实测数字：")
    for name, m in CANDIDATES.items():
        print(f"  {name:<14}通过率 {m['pass_rate']:.0%}   成本 ¥{m['avg_cost']:.4f}   "
              f"P95 {m['p95_latency_ms']:.0f}ms")

    print("\n" + "=" * 88)
    print("为什么结论会不一样：门禁不是'客观真理'，是'业务选择'")
    print("=" * 88)
    for gname, gate in GATES.items():
        blocked = [n for n, m in CANDIDATES.items() if not judge(m, gate).passed]
        print(f"  {gname}")
        for key, (op, limit) in gate.items():
            print(f"    {key:<16}{op:>3}{limit:>10.4g}")
        print(f"    → 拦下：{blocked or '无'}")

    print("\n" + "=" * 88)
    print("三个必须写进文档的规则")
    print("=" * 88)
    print("  1. **门禁要跟着业务场景走**：内部工具能容忍 75% 通过率，法务系统不能。")
    print("  2. **阈值要有出处**：写在 PR 描述 / 设计文档里，并说明'为什么是这个数'。")
    print("     写不出'为什么'的阈值，本质上就是拍脑袋。")
    print("  3. **门禁只能防退化，不能证明优秀**：")
    print("     通过门禁 = '没变差'，不等于'够好了'。'够好'要靠第 40 章的绝对指标。")

    print("\n" + "=" * 88)
    print("一个真实会踩的坑：把'average'当门禁")
    print("=" * 88)
    # 假设 100 条用例：90 条全对，另 10 条是"发票冲红"这一类，全错
    buckets = {"一般问题": (90, 90), "发票冲红": (0, 10)}
    total_hit = sum(h for h, _ in buckets.values())
    total_n = sum(n for _, n in buckets.values())
    print(f"  总体：{total_hit}/{total_n} = {total_hit / total_n:.0%}   → 全绿")
    for name, (hit, n) in buckets.items():
        print(f"    {name:<8}{hit}/{n} = {hit / n:.0%}")
    print("  → 一个分类 0%、总体仍 90%：**总体指标会把'某一类彻底坏掉'掩盖成'整体良好'。**")
    print("     所以门禁至少要有两项：总体率 + 分类最低率。")


if __name__ == "__main__":
    main()
