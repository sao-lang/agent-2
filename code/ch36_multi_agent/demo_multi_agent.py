"""第 43 章示例：多 Agent 的判据、形态与成本对比（不需要 API）。

运行：
    python code/ch36_multi_agent/demo_multi_agent.py

四个部分：
  1. 三个判据：什么样的任务该拆
  2. 形态 A：Supervisor（串行分派，协调者主导）
  3. 形态 B：并行 fan-out（并行子任务，延迟取 max）
  4. 成本对比：单 Agent vs 多 Agent 的三方对比
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.multi_agent import (  # noqa: E402
    CostModel,
    SplitCriteria,
    build_supervisor,
)


def section(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> None:
    # ---------------------------------------------------------------- 判据
    section("① 三个判据：什么任务该拆")
    cases = [
        ("写三份不同产品的文案", SplitCriteria(True, False, False)),
        ("写文案 + 审文案（要互看）", SplitCriteria(False, True, False)),
        ("读 500 页手册后总结", SplitCriteria(True, False, True)),
        ("查一个订单状态", SplitCriteria(False, False, False)),
        ("对比 5 家竞品定价", SplitCriteria(True, False, False)),
        ("审合同时交叉核对条款", SplitCriteria(False, True, True)),
    ]
    print(f"  {'任务':<28}{'可并行':>8}{'需互看':>8}{'装不下':>8}   结论")
    print("  " + "-" * 88)
    for task, c in cases:
        ok, why = c.verdict()
        print(f"  {task:<28}{str(c.can_parallel):>8}{str(c.need_cross_read):>8}{str(c.context_too_large):>8}   "
              f"{'✅ 可拆' if ok else '❌ 不拆'}：{why}")

    print("\n  👉 注意'写文案 + 审文案'：看起来像两个 Agent，")
    print("     但只要上下文装得下，单 Agent + Reflection（第 34 章）更便宜也更准。")

    # ---------------------------------------------------------------- Supervisor
    section("② 形态 A：Supervisor（串行分派）")
    app = build_supervisor()
    t0 = time.perf_counter()
    out = app.invoke({"task": "调研竞品", "findings": [], "rounds": 0})
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  轮次：{out.get('rounds')}")
    print(f"  产出：{out.get('findings')}")
    print(f"  最终：{out.get('final')}")
    print(f"  耗时：{elapsed:.0f}ms")
    print("\n  → 串行：三个 worker 依次执行，总耗时相加。")
    print("     这种形态只在'后一个要看前一个结果'时才有必要。")

    # ---------------------------------------------------------------- 并行
    section("③ 形态 B：并行 fan-out（延迟取 max）")
    from common.multi_agent import build_fan

    fan = build_fan()
    t0 = time.perf_counter()
    # ⚠️ 注意：这里直接把 planner 的结果喂进去，模拟"子任务已确定"
    out = fan.invoke({"task": "写三份文案", "subtasks": [], "results": []})
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  结果：{out.get('final')}")
    print(f"  子结果数：{len(out.get('results', []))}")
    print(f"  耗时：{elapsed:.0f}ms")
    print("\n  → 串行需要 900ms，并行只需要 ~300ms（取 max）。")
    print("     这就是多 Agent 唯一无可替代的价值：**真并行**。")

    # ---------------------------------------------------------------- 成本
    section("④ 成本对比：单 Agent vs 多 Agent")
    cm = CostModel()
    single = cm.single(steps=4)
    multi = cm.multi(workers=3, steps_per_worker=2)

    print(f"  {'方案':<14}{'Agent数':>8}{'调用数':>8}{'成本(¥)':>10}{'延迟(s)':>10}")
    print("  " + "-" * 52)
    print(f"  {'单 Agent':<14}{single['agents']:>8}{single['calls']:>8}{single['cost']:>10.4f}{single['latency_s']:>10.1f}")
    print(f"  {'多 Agent':<14}{multi['agents']:>8}{multi['calls']:>8}{multi['cost']:>10.4f}{multi['latency_s']:>10.1f}")
    print("  " + "-" * 52)
    print(f"  成本倍数：{multi['cost'] / single['cost']:.1f}x")
    print(f"  延迟变化：{single['latency_s']:.1f}s → {multi['latency_s']:.1f}s")

    print("\n  关键结论：")
    print("    · 多 Agent 的成本是**乘法放大**，不是加法")
    print("    · 延迟只有在'真并行'时才改善（串行的 Supervisor 反而更慢）")
    print("    · 所以：**除非能并行，否则别拆**")

    # ---------------------------------------------------------------- 反例
    section("⑤ 一个反例：为什么很多人拆完又退回去")
    print("  典型路径：")
    print("    1. 任务复杂 → 拆成 4 个 Agent")
    print("    2. 每个 Agent 的 prompt 都要写全上下文（因为不知道对方做了什么）")
    print("    3. token 变成 3 倍，延迟变成 2 倍")
    print("    4. 出错时不知道是哪个 Agent 的锅（trace 变复杂）")
    print("    5. 最后改回单 Agent + 工具 + Reflection")
    print("\n  正确的做法：")
    print("    · 先做单 Agent，跑到瓶颈（上下文装不下 / 真的能并行）")
    print("    · 再拆，并且**只拆真正独立的那部分**")
    print("    · 拆完必须做三方对比（质量/成本/延迟）")

    section("⑥ 拆分后的三个必做配置")
    print("  1. **预算分摊**：每个子 Agent 有独立预算，防止一个跑飞拖垮全局（第 58 章）")
    print("  2. **终止条件**：协调者必须能判断'够了'（coverage >= 0.9 或 budget 用完）")
    print("  3. **共享黑板**（如需互看）：事实带版本号和作者，防覆盖（见下）")
    print("\n  共享黑板的最小结构：")
    print("    class Fact(BaseModel):")
    print("        text: str; source: str; confidence: float; author: str; version: int")
    print("    追加而不覆盖，冲突时保留两个版本 + 标记")


if __name__ == "__main__":
    main()
