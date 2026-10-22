"""第 36 章 step4：流水线 —— 边检索边生成，让首字早出来（离线）。

运行：
    python code/ch36_latency/step4_pipeline.py

上一级的痛点：并行只解决了"三路检索"，但检索 → 生成仍然串行。
这一级做什么：让生成在**第一批检索结果到了**就开始，而不是等全部。

三个方案：
  A 全部检索完 → 再生成
  B 分批检索 → 第一批到了就生成
  C 先给用户看"正在查资料"（进度反馈）

关键洞察：**流水线优化的是"体感"，不是"总时长"。**
"""
from __future__ import annotations

import time

# 检索批次（真实系统里，这可能是"先粗召回、再精排"）
BATCHES = [
    ("第一批（粗召回 20 条）", 220),
    ("第二批（精排 top5）", 320),
    ("第三批（补充上下文）", 260),
]
GEN_FIRST_TOKEN = 640     # 首字
GEN_TOTAL = 1400          # 完整生成


def scheme_a() -> dict[str, float]:
    """全部检索完再生成。"""
    t0 = time.perf_counter()
    for _name, ms in BATCHES:
        time.sleep(ms / 1000)
    retrieve_done = (time.perf_counter() - t0) * 1000

    time.sleep(GEN_FIRST_TOKEN / 1000)
    ttft = (time.perf_counter() - t0) * 1000

    time.sleep((GEN_TOTAL - GEN_FIRST_TOKEN) / 1000)
    total = (time.perf_counter() - t0) * 1000
    return {"retrieve": retrieve_done, "ttft": ttft, "total": total}


def scheme_b() -> dict[str, float]:
    """第一批检索到了就开始生成，后续批次在生成过程中补充。"""
    t0 = time.perf_counter()

    # 第一批检索
    name0, ms0 = BATCHES[0]
    time.sleep(ms0 / 1000)
    first_ready = (time.perf_counter() - t0) * 1000

    # 首字（此时背景里还在跑第 2、3 批）
    time.sleep(GEN_FIRST_TOKEN / 1000)
    ttft = (time.perf_counter() - t0) * 1000

    # 剩余的检索批次与生成并行
    rest = sum(ms for _, ms in BATCHES[1:]) / 1000
    gen_rest = (GEN_TOTAL - GEN_FIRST_TOKEN) / 1000
    time.sleep(max(rest, gen_rest))
    total = (time.perf_counter() - t0) * 1000
    return {"retrieve": first_ready, "ttft": ttft, "total": total}


def main() -> None:
    print("=" * 78)
    print("① 检索批次")
    print("=" * 78)
    for name, ms in BATCHES:
        print(f"    {name:<24}{ms:>5}ms")
    print(f"    检索合计 {sum(ms for _, ms in BATCHES)}ms ｜ "
          f"生成首字 {GEN_FIRST_TOKEN}ms ｜ 生成总计 {GEN_TOTAL}ms")

    a = scheme_a()
    b = scheme_b()

    print("\n" + "=" * 78)
    print("② 两种调度")
    print("=" * 78)
    print(f"  {'方案':<28}{'首字(TTFT)':>14}{'总耗时':>12}")
    print("  " + "-" * 56)
    print(f"  {'A 全部检索完再生成':<28}{a['ttft']:>13.0f}ms{a['total']:>11.0f}ms")
    print(f"  {'B 第一批到了就生成':<28}{b['ttft']:>13.0f}ms{b['total']:>11.0f}ms")

    d_ttft = a["ttft"] - b["ttft"]
    d_total = a["total"] - b["total"]
    print()
    print(f"  首字：快 {d_ttft:.0f}ms（{d_ttft / a['ttft']:.0%}）")
    print(f"  总耗时：省 {d_total:.0f}ms（{d_total / a['total']:.0%}）—— 这部分来自『不再空等第三批』")

    print("\n" + "=" * 78)
    print("★ 关键洞察：流水线优化的是『体感』，不是『总时长』")
    print("=" * 78)
    print(f"  总时长从 {a['total']:.0f}ms 降到 {b['total']:.0f}ms，主要是因为第三批检索被生成过程吞掉了；")
    print(f"  但真正的收益在首字：{a['ttft']:.0f}ms -> {b['ttft']:.0f}ms（{d_ttft / a['ttft']:.0%}），")
    print(f"  用户在 {b['ttft']:.0f}ms 就看到了第一个字，")
    print("  **他的『等待焦虑』从那一刻起就解除了**。")
    print()
    print("  这也是为什么流式输出（SSE / chunked）几乎总是值得做：")
    print("  它不缩短任何计算，但把『一片空白』变成了『字在往外冒』。")

    print("\n" + "=" * 78)
    print("③ 流水线的三个必要前提")
    print("=" * 78)
    print("  1. 第一批结果必须**够用**")
    print("     如果第一批只有 3 条而且质量差，生成出来的东西后面还得推翻重来。")
    print("     → 实践：第一批用『粗召回 + 快速过滤』，保证不跑偏；精排结果后面再补。")
    print()
    print("  2. 生成必须**可中断/可续写**")
    print("     后面补到更好的材料时，要能决定『忽略』还是『重写』。")
    print("     → 简单做法：只补细节，不改结论；需要改结论就重跑。")
    print()
    print("  3. 必须能**解释给用户**")
    print("     用户看到字在输出，但内容是基于第一批材料的。")
    print("     → 如果后面材料推翻了结论，必须显式更正，不能悄悄改。")

    print("\n" + "=" * 78)
    print("④ 最便宜的一招：先给反馈")
    print("=" * 78)
    print("  如果流水线改不动（比如检索依赖强），还有一招：")
    print("    在 0ms 就返回一句话：『正在为你查询售后政策…』")
    print("  它不缩短任何延迟，但把『系统卡了』变成『系统在处理』。")
    print()
    print("  ⚠️ 但别滥用：每次都显示『正在思考…』最后却给出个错误答案，")
    print("     比什么提示都没有更让人恼火。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print(f"  首字 {a['ttft']:.0f}ms → {b['ttft']:.0f}ms（-{d_ttft / a['ttft']:.0%}），")
    print(f"  总时长 {a['total']:.0f}ms → {b['total']:.0f}ms（省 {d_total / a['total']:.0%}）。")
    print("  这是本章最划算的一次改动：不改任何检索算法，只改调度顺序。")


if __name__ == "__main__":
    main()
