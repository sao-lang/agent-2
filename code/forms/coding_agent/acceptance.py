"""验收的五个数：成功率（带区间）、平均步数、diff 命中率、人工返工率、单任务成本。

不联网。用 agent_loop 的六步剧本跑 20 次，前一半"第一次假设就对"，后一半"第一次修错方向"，
因此成功率不是 100%，这张表才看得出来区间与成本的算法。

运行：python code/forms/coding_agent/acceptance.py
"""

from __future__ import annotations

import math

from agent_loop import run_once

PRICE_PER_MTOK = 2.0          # 假设单价：2 元 / 百万 token（只用于把 token 换算成钱）


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 区间。小样本下比 k/n 加减标准误可靠。"""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def main() -> None:
    runs = [run_once(seed=i) for i in range(20)]

    n = len(runs)
    wins = sum(1 for r in runs if r.green and r.hidden_green)
    steps = sum(len(r.steps) for r in runs) / n
    tokens = sum(r.tokens for r in runs) / n
    # 这类任务的目标函数只有一个（average），每一次补丁都落在它上面
    hit = sum(1 for r in runs if any(s.tool == "apply_patch" for s in r.steps)) / n
    rework = sum(1 for r in runs if not (r.green and r.hidden_green)) / n
    cost = tokens / 1_000_000 * PRICE_PER_MTOK

    lo, hi = wilson(wins, n)
    print("=== 1. 五个数 ===")
    print(f"    运行数            {n}")
    print(f"    成功率            {wins}/{n} = {wins / n:.2f}   95% 区间 [{lo:.2f}, {hi:.2f}]")
    print(f"    平均步数          {steps:.2f}")
    print(f"    diff 命中率       {hit:.0%}（补丁落在目标函数 average 上）")
    print(f"    人工接手率        {rework:.0%}（最终没绿，需要人接着做）")
    print(f"    单任务成本        {tokens:.0f} tokens ≈ {cost:.6f} 元（按 {PRICE_PER_MTOK} 元/百万）")

    print()
    print("=== 2. 为什么成功率必须带区间 ===")
    print(f"    20 次里成功 {wins} 次，点估计 {wins / n:.2f}")
    print(f"    同一批数据，95% 置信区间是 [{lo:.2f}, {hi:.2f}]，宽度 {(hi - lo) * 100:.0f} 个百分点")
    print("    写'成功率 75%'会让读者以为再跑一次还是 75%；区间说的是'真实值大概落在这一段'")
    print("    要判断两个版本谁更好，区间重叠时不能用'我的数大'当结论（第 45 章 E9）")

    print()
    print("=== 3. 成本的两个口径 ===")
    print(f"    每次运行            {tokens:.0f} tokens")
    print(f"    每成功一次          {tokens * n / wins:.0f} tokens")
    print("    后者才是可比的：失败的那一半也要付钱，而且往往付得更多（多一轮补丁与测试）")
    by_mode = {m: [r for r in runs if r.mode == m] for m in (0, 1, 2)}
    for m, label in ((0, "一次就对"), (1, "修错一次后改对"), (2, "两次都错")):
        rs = by_mode[m]
        if rs:
            print(f"    {label:<12}{len(rs)} 次，平均 {sum(len(r.steps) for r in rs) / len(rs):.1f} 步，"
                  f"平均 {sum(r.tokens for r in rs) / len(rs):.0f} tokens")

    print()
    print("=== 4. 这张表不能回答什么 ===")
    print("    它测的是'这个剧本 + 这个小仓库'，不是模型的通用编码能力")
    print("    它没有覆盖：跨文件改动、并发编辑、依赖升级、测试本身写错")


if __name__ == "__main__":
    main()
