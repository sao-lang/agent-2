"""第 10 章 · 成本上界：固定工作流为什么能"算"出最坏成本。

运行：
    python code/ch10_fixed_workflow/step3_cost_ceiling.py

关键差别：
  · 固定工作流的路径可以**枚举**，所以最坏成本是一个加法。
  · ReAct 的路径无法枚举（模型每步都可能继续），所以只能设上限，不能算上界。

注意本脚本同时演示一个坑：**枚举出来的"最坏路径"未必真实存在。**
"""
from __future__ import annotations

PRICE_PER_1K = 0.0012       # 元 / 1,000 token（示意价，按自己的模型改）
DAILY_CALLS = 3000

# 路径名 → [(节点, 输入 token, 输出 token)]
PATHS: dict[str, list[tuple[str, int, int]]] = {
    "hit": [("改写", 60, 20), ("生成", 520, 140)],
    "miss": [("改写", 60, 20), ("生成", 430, 60)],
}

# 一条真实流量里几乎不会出现、但结构上存在的路径（用来演示"上界被虚高"）
PHANTOM = {"edge": [("改写", 60, 20), ("生成", 520, 140), ("转人工", 800, 200)]}

# 真实路径分布（从日志统计），用来对比"上界"和"平均值"
DISTRIBUTION = {"hit": 0.80, "miss": 0.20}


def total(path: list[tuple[str, int, int]]) -> int:
    return sum(i + o for _, i, o in path)


def money(tokens: int) -> float:
    return tokens / 1000 * PRICE_PER_1K


def report(paths: dict[str, list[tuple[str, int, int]]], title: str) -> None:
    print(title)
    print(f"{'路径':<8}{'节点数':>6}{'输入token':>11}{'输出token':>11}{'合计token':>11}")
    print("-" * 47)
    for name, path in paths.items():
        i = sum(x for _, x, _ in path)
        o = sum(x for _, _, x in path)
        print(f"{name:<8}{len(path):>6}{i:>11}{o:>11}{total(path):>11}")
    worst = max(paths.values(), key=total)
    print(f"\n可枚举路径：{len(paths)} 条")
    print(f"成本上界：{total(worst)} token/次   ¥{money(total(worst)):.6f}/次")
    print(f"按 {DAILY_CALLS:,} 次/日估算：¥{money(total(worst)) * DAILY_CALLS:.2f}/日")


def main() -> None:
    print("=" * 47)
    report(PATHS, "只看真实存在的路径")
    print("=" * 47)

    print("\n" + "=" * 47)
    inflated = {**PATHS, **PHANTOM}
    report(inflated, "把一条结构上存在、流量里不存在的路径也算进去")
    print("=" * 47)
    print(f"\n虚高倍数：{total(PHANTOM['edge']) / max(total(p) for p in PATHS.values()):.2f}x")
    print("→ 只算上界会被自己吓住，只算平均会漏掉贵分支。两者都要量。")

    print("\n" + "=" * 47)
    print("上界 vs 平均值")
    print("=" * 47)
    avg = sum(total(PATHS[k]) * w for k, w in DISTRIBUTION.items())
    up = max(total(p) for p in PATHS.values())
    print(f"  上界：{up} token/次")
    print(f"  平均：{avg:.0f} token/次（hit 80% / miss 20%）")
    print(f"  日成本：上界 ¥{money(up) * DAILY_CALLS:.2f} / 平均 ¥{money(int(avg)) * DAILY_CALLS:.2f}")

    print("\n" + "=" * 47)
    print("对照 ReAct 为什么算不出来")
    print("=" * 47)
    print("  ReAct 的路径数取决于模型每一轮是否继续调用工具，")
    print("  结构上就是一棵不断分叉的树 —— 无法枚举，只能设 max_steps。")
    print("  所以它只能给「上限」，给不了「上界」。")

    assert up > avg, "上界必须不小于平均值"


if __name__ == "__main__":
    main()
