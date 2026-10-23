"""第 36 章 step1：为什么"平均 2 秒"用户还是觉得慢（离线）。

运行：
    python code/ch36_latency/step1_average_lies.py

上一级的痛点：无（这是起点）。
这一级做什么：用同一批延迟数据，算三个"平均"之外的数字 ——
             你会发现"平均值达标"和"用户体验好"根本不是一回事。

三个必看的数：
  p50  一半的请求比它快
  p95  5% 的请求比它慢 —— **这才是用户抱怨的来源**
  尾部占比  慢请求占多少
"""
from __future__ import annotations

import statistics

# 一次真实压测的 40 个请求耗时（毫秒），故意留了一条长尾
SAMPLES = [
    1820, 1950, 2040, 2110, 2190, 2230, 2280, 2320, 2350, 2390,
    2410, 2450, 2480, 2500, 2530, 2560, 2600, 2640, 2680, 2710,
    2750, 2790, 2840, 2890, 2930, 2980, 3050, 3120, 3200, 3300,
    3450, 3600, 3800, 4100, 4500, 5200, 6100, 7400, 9800, 14500,
]

# SLO：95% 的请求应该在 3 秒内
SLO_MS = 4000


def percentile(sorted_vals: list[int], p: float) -> float:
    """线性插值百分位（和很多监控系统一致）。"""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main() -> None:
    vals = sorted(SAMPLES)
    n = len(vals)
    mean = statistics.fmean(vals)
    p50 = percentile(vals, 0.50)
    p90 = percentile(vals, 0.90)
    p95 = percentile(vals, 0.95)
    p99 = percentile(vals, 0.99)

    print("=" * 74)
    print(f"压测样本：{n} 个请求")
    print("=" * 74)
    print(f"  平均  {mean:>8.0f} ms")
    print(f"  p50   {p50:>8.0f} ms   ← 一半请求比它快")
    print(f"  p90   {p90:>8.0f} ms")
    print(f"  p95   {p95:>8.0f} ms   ← 5% 的请求比它慢")
    print(f"  p99   {p99:>8.0f} ms")
    print(f"  最大  {vals[-1]:>8.0f} ms")

    print("\n" + "=" * 74)
    print(f"★ 平均 {mean:.0f}ms 「达标」，但 p95 = {p95:.0f}ms 远超 SLO（{SLO_MS}ms）")
    print("=" * 74)
    over = [v for v in vals if v > SLO_MS]
    print(f"  超过 {SLO_MS}ms 的请求：{len(over)} 个（{len(over) / n:.0%}）")
    print(f"  最慢几个：{[round(v) for v in vals[-6:]]}")
    print()
    verdict = "达标" if mean <= SLO_MS else "不达标"
    print(f"  如果只看平均（{mean:.0f}ms vs SLO {SLO_MS}ms → {verdict}），"
          f"{'你会以为一切正常。' if mean <= SLO_MS else '你会去优化平均值。'}")
    print(f"  但实际有 {len(over)} 个用户等了超过 {SLO_MS}ms —— 他们才是会写差评的人。")
    print(f"  p95 = {p95:.0f}ms，是 SLO 的 {p95 / SLO_MS:.1f} 倍。")

    print("\n" + "=" * 74)
    print("★ 为什么平均值会骗人")
    print("=" * 74)
    print("  延迟分布是**右偏**的（有长尾），不是正态分布。")
    print("  平均值被大量『还行』的请求拉低，掩盖了少数『极慢』的请求。")
    print()
    print("  举个极端例子：")
    print("    39 个请求各 2 秒，1 个请求 60 秒")
    print(f"    平均 = {(39 * 2 + 60) / 40:.1f} 秒  ← 看起来『还行』")
    print("    p95  = 2 秒（因为 95% 分位正好落在 2 秒那批里）")
    print("    但那个等 60 秒的用户，已经卸载了。")
    print()
    print("  → 所以延迟报表必须给 **p50 / p95 / p99**，而不只是平均。")

    print("\n" + "=" * 74)
    print("★ 更关键：用户感知的是哪一段")
    print("=" * 74)
    print("  上面这些数字都是**总延迟**（最后一次调用返回）。")
    print("  但用户真正在等的是 **TTFT（首字延迟）**——")
    print("  他盯着屏幕，第一句话什么时候出来。")
    print()
    print("  典型 RAG 请求的分解（本仓库 demo_latency.py 的实测比例）：")
    print("    意图识别 120ms + 改写 260ms + 检索 240ms + BM25 80ms + 重排 180ms")
    print("    = 880ms 之后，模型才开始出第一个字")
    print("    然后再花 640ms 才吐出第一个 token")
    print()
    print("  也就是说：**总延迟 3400ms 里，用户前 1520ms 看到的是一片空白。**")
    print("  优化『模型生成』（1880ms）会让总时长变短，但用户还是觉得『点了没反应』。")

    print("\n" + "=" * 74)
    print("结论")
    print("=" * 74)
    print("  三个必看的数：p50（体感基准）、p95（SLO）、TTFT（用户实际在等的）。")
    print("  下一级把一次请求拆成时间轴，让你看见『空白』到底花在哪。")


if __name__ == "__main__":
    main()
