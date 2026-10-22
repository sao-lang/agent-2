"""第 35 章 step2：三个杠杆，按收益排序（离线）。

运行：
    python code/ch34_cost/step2_levers.py

上一级的痛点：知道钱花在哪了，但"该动哪一个"还没量化。
这一级做什么：把四个常见杠杆放到同一批请求上跑一遍，给出各自的收益。

四个杠杆：
  L1 精确缓存     同样的问题直接复用答案
  L2 模型路由     简单环节换便宜模型
  L3 上下文裁剪   少喂没用的历史（第 31 章）
  L4 预算上限     不省钱，但防事故

⚠️ 顺序很重要：L1 和 L4 便宜且立刻见效，先做；L3 收益要过评测才敢上。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cost import ExactCache  # noqa: E402
from common.meter import CallRecord  # noqa: E402

# 一天 200 次请求里，有 40% 是重复问题（客服场景的典型分布）
N_REQUESTS = 200
DUP_RATIO = 0.40

# 单次请求的典型消耗（与 step1 同一组数字）
STAGES = [
    ("intent", "qwen-plus", 180, 30),
    ("retrieve-query-rewrite", "qwen-plus", 260, 40),
    ("plan", "deepseek-chat", 900, 300),
    ("answer", "deepseek-chat", 3600, 600),
    ("reflect", "deepseek-chat", 5200, 200),
]


def request_cost(tier_map: dict[str, str], history_tokens: int = 0) -> float:
    """跑一次请求，返回成本。tier_map 用来做模型路由。"""
    total = 0.0
    for stage, model, tin, tout in STAGES:
        m = tier_map.get(stage, model)
        extra = history_tokens if stage in ("answer", "reflect") else 0
        total += CallRecord(model=m, step=stage, input_tokens=tin + extra, output_tokens=tout).cost
    return total


def main() -> None:
    base = request_cost({})
    baseline = base * N_REQUESTS

    print("=" * 70)
    print(f"基线：{N_REQUESTS} 次请求，每次 ¥{base:.6f}")
    print("=" * 70)
    print(f"  一天总成本：¥{baseline:.4f}")

    # L1 精确缓存
    cache = ExactCache()
    hits = 0
    for i in range(N_REQUESTS):
        prompt = f"问题 {i % int(N_REQUESTS * (1 - DUP_RATIO))}"   # 后 40% 是重复
        if cache.get(prompt, "deepseek-chat") is None:
            cache.put(prompt, "deepseek-chat", "答案")
        else:
            hits += 1
    l1 = baseline * (1 - cache.hit_rate)

    # L2 模型路由：简单环节换便宜模型
    routed = request_cost({"intent": "qwen-plus", "retrieve-query-rewrite": "qwen-plus",
                           "plan": "qwen-plus", "answer": "deepseek-chat", "reflect": "qwen-plus"})
    l2 = routed * N_REQUESTS

    # L1 + L2 叠加
    l12 = l2 * (1 - cache.hit_rate)

    # L3 上下文裁剪：假设历史平均 1500 token，裁掉一半
    trimmed = request_cost({}, history_tokens=-750)
    l3 = trimmed * N_REQUESTS

    print("\n" + "=" * 70)
    print("四个杠杆，各自单独跑")
    print("=" * 70)
    rows = [
        ("基线（什么都不做）", baseline, 0.0),
        ("L1 精确缓存", l1, cache.hit_rate),
        ("L2 模型路由", l2, None),
        ("L3 上下文裁剪（历史 -750 token）", l3, None),
        ("L1 + L2 叠加", l12, None),
    ]
    print(f"{'方案':<34}{'一天成本(¥)':>14}{'相对基线':>12}")
    print("-" * 70)
    for name, cost, _ in rows:
        delta = (cost - baseline) / baseline
        mark = "—" if abs(delta) < 1e-9 else f"{delta:+.0%}"
        print(f"{name:<34}{cost:>14.4f}{mark:>12}")

    print("\n" + "=" * 70)
    print("★ 为什么『缓存』排在第一位")
    print("=" * 70)
    print(f"  本场景重复率 {DUP_RATIO:.0%}（客服的真实分布），")
    print(f"  缓存命中率 {cache.hit_rate:.0%}，成本直接降 {cache.hit_rate:.0%}（省下的部分就是命中的部分）。")
    print()
    print("  它便宜在哪：")
    print("    · 零模型调用（不是『更省的调用』，是**完全不调用**）")
    print("    · 延迟从秒级降到毫秒级（第 36 章）")
    print("    · 实现成本：一张 dict + 一个 hash 函数")
    print()
    print("  它贵在哪（风险）：")
    print("    · 命中键必须是『完全一样』的输入（prompt + model + 关键参数）")
    print("    · 有状态的数据不能缓存（库存、余额、订单状态）")
    print("    · 缓存过期策略设计错了会发出过时答案")

    print("\n" + "=" * 70)
    print("★ 模型路由的边界：不是所有环节都能降级")
    print("=" * 70)
    print(f"  {'环节':<24}{'降级风险'}")
    print("  " + "-" * 52)
    print(f"  {'intent':<24}{'低 —— 分类错了顶多答非所问一环'}")
    print(f"  {'retrieve-query-rewrite':<24}{'低 —— 改写差一点，召回靠排序兜底'}")
    print(f"  {'plan':<24}{'中 —— 计划质量直接影响后续所有步骤'}")
    print(f"  {'answer':<24}{'**高 —— 这是用户直接看到的东西，别降**'}")
    print(f"  {'reflect':<24}{'中 —— 反思本身可以弱一点，但结论要保留'}")
    print()
    print("  判据：**输出直接给用户看的环节，不要降级。**")
    print("  中间环节（分类、改写、抽取）才是降级的主战场。")

    print("\n" + "=" * 70)
    print("★ L4 预算上限：它不省钱，但防事故")
    print("=" * 70)
    print("  一个典型的失控场景：Agent 陷入循环，一次请求烧了 200 次调用。")
    print(f"  按本基线 ¥{base:.6f}/次算，一次事故 = ¥{base * 200:.2f}；")
    print("  如果一天来 10 次，就是几十块——单看不多，但月末对账时你会看到一条突兀的尖峰。")
    print()
    print("  预算上限的价值不是『平均成本降低』，而是**把长尾切掉**。")
    print("  它是唯一一个『不做优化也能立刻止损』的杠杆。")

    print("\n" + "=" * 70)
    print("推荐顺序")
    print("=" * 70)
    print("  1. L4 预算上限     —— 今天就能加，防最坏情况")
    print("  2. L1 精确缓存     —— 一天能做完，通常立省 30%+")
    print("  3. L2 模型路由     —— 一周，先降中间环节")
    print("  4. L3 上下文裁剪   —— 必须过评测（省一点但可能掉点）")
    print()
    print("  ⚠️ 所有优化都必须一起报『成本』和『质量』两个数（第 40 章）。")


if __name__ == "__main__":
    main()
