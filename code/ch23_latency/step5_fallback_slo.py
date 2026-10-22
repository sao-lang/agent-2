"""第 23 章 step5：降级链与 SLO —— 卡死比慢更可怕（离线）。

运行：
    python code/ch23_latency/step5_fallback_slo.py

上一级的痛点：并行、流水线都用上了，但**模型挂了/超时**时还是会卡住。
这一级做什么：用一条"逐级退让"的降级链保住可用性，并把 SLO 写成可验证的判据。

降级链的核心不是"变快"，而是**"保证在 X 毫秒内一定有东西返回"**。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Stage:
    name: str
    timeout_ms: int
    latency_ms: int        # 这一级的正常耗时
    ok: bool = True        # False 表示这一级当前不可用
    quality: str = ""


CHAIN = [
    Stage("strong-model", timeout_ms=2500, latency_ms=2400, ok=True, quality="最好"),
    Stage("cheap-model", timeout_ms=3000, latency_ms=900, ok=True, quality="够用"),
    Stage("cache-or-template", timeout_ms=1000, latency_ms=120, ok=True, quality="有限"),
    Stage("fallback-message", timeout_ms=200, latency_ms=20, ok=True, quality="最低（但要能看懂）"),
]

# SLO：99% 的请求必须在 4 秒内拿到"至少能看"的回答
SLO_MS = 4000


def run_chain(stages: list[Stage]) -> tuple[str, float, str]:
    """逐级尝试，返回（成功的级名, 累计耗时, 质量等级）。"""
    elapsed = 0.0
    for st in stages:
        if not st.ok:
            continue
        budget = min(st.timeout_ms, SLO_MS - elapsed)
        if budget <= 0:
            break
        used = min(st.latency_ms, budget)
        elapsed += used
        if st.latency_ms <= budget:
            return st.name, elapsed, st.quality
        # 超时 → 继续下一级
    return "none", elapsed, "无"


def show(label: str, stages: list[Stage]) -> None:
    name, ms, q = run_chain(stages)
    mark = "OK" if ms <= SLO_MS and name != "none" else "超 SLO"
    print(f"  {label:<34}→ {name:<20}{ms:>7.0f}ms  质量={q:<16}{mark}")


def main() -> None:
    print("=" * 82)
    print("① 降级链（逐级退让）")
    print("=" * 82)
    print(f"  {'级别':<22}{'超时':>8}{'正常耗时':>10}  质量")
    print("  " + "-" * 60)
    for st in CHAIN:
        print(f"  {st.name:<22}{st.timeout_ms:>7}ms{st.latency_ms:>9}ms  {st.quality}")

    print("\n" + "=" * 82)
    print("② 四种情况下，最终谁兜住了")
    print("=" * 82)
    show("全部正常", CHAIN)

    def clone(st: Stage, **kw) -> Stage:
        d = st.__dict__.copy()
        d.update(kw)
        return Stage(**d)

    degraded = [clone(CHAIN[0], ok=False)] + CHAIN[1:]
    show("strong-model 挂了", degraded)

    slow = [clone(CHAIN[0], latency_ms=20000)] + CHAIN[1:]
    show("strong-model 卡死（20s）", slow)

    down2 = [clone(CHAIN[0], ok=False), clone(CHAIN[1], ok=False)] + CHAIN[2:]
    show("前两级都挂了", down2)

    print("\n" + "=" * 82)
    print("★ 关键：『卡死 20 秒』和『慢 900ms 但成功』")
    print("=" * 82)
    print("  上面第 3 行就是核心场景：strong-model 没有报错，只是很慢（20s）。")
    print("  如果没有降级链，用户会一直等到它返回 —— 然后大概率已经关掉页面了。")
    print("  有了降级链，2500ms 超时后立刻切到 cheap-model，最终在 SLO 内给了答案。")
    print()
    print("  ⚠️ 注意：每一步的 timeout 都必须**小于** SLO 剩余时间，")
    print("     否则『超时』这个动作本身就把预算吃光了 —— 这正是第 4 行发生的事。")
    print()
    print("  → 这就是延迟工程里最反直觉的一条：")
    print("     **『快速给出一个还行的答案』比『慢慢给出最好的答案』更有价值。**")

    print("\n" + "=" * 82)
    print("③ SLO 怎么写才可验证")
    print("=" * 82)
    print("  ❌ 『响应要快』          —— 没法验收")
    print("  ❌ 『平均 < 2 秒』       —— 平均值会骗人（step1）")
    print("  ✅ 『p95 TTFT <= 1.5s 且 99% 请求 <= 4s 内返回可用答案』")
    print()
    print("  三个要素：")
    print("    1. 指标（TTFT / 总时长）")
    print("    2. 分位（p95 / p99，不是平均）")
    print("    3. 『可用答案』的定义 —— 降级到 template 也算，但不能是空")

    print("\n" + "=" * 82)
    print("④ 降级链的三个设计约束")
    print("=" * 82)
    print("  1. 每一级都必须**真的快**")
    print("     如果 cheap-model 也要 5 秒，那它就不是降级，是换个方式等。")
    print()
    print("  2. 兜底消息必须**有信息量**")
    print("     ❌ 『系统繁忙，请稍后再试』")
    print("     ✅ 『查到了 3 条相关政策，但生成回答超时了，你可以直接看原文：[链接]』")
    print()
    print("  3. 降级要**可观测**")
    print("     每次降级都记一条：从哪一级降到哪一级、为什么。")
    print("     否则你永远不知道 SLO 是靠『真的快了』还是『一直在降级』撑住的。")

    print("\n" + "=" * 82)
    print("结论")
    print("=" * 82)
    print("  降级链不优化延迟，它**兜住延迟的下限**。")
    print("  一个没有降级链的系统，任何一次模型抖动都会变成一次用户流失。")


if __name__ == "__main__":
    main()
