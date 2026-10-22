"""第 23 章 step2：瀑布图 —— 把"一片空白"拆成时间段（离线）。

运行：
    python code/ch23_latency/step2_waterfall.py

上一级的痛点：知道 p95 超标，但不知道**超在哪一段**。
这一级做什么：记录每个阶段的开始/结束，画出时间轴，并算两个不同的"总时长"。

两个总时长：
  TTFT  从请求到第一个 token      ← 用户体感
  整体  从请求到最后一个 token     ← 账单与容量

同一张瀑布图，两个数字，优化手法完全不同。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Phase:
    name: str
    start_ms: float
    dur_ms: float
    kind: str          # "pre"（生成前） / "llm"（生成中） / "post"


@dataclass
class Waterfall:
    phases: list[Phase] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)
    _open: dict[str, float] = field(default_factory=dict)

    def start(self, name: str) -> None:
        self._open[name] = (time.perf_counter() - self._t0) * 1000

    def end_at(self, name: str, kind: str = "pre") -> None:
        """记录某阶段的结束时刻并算出耗时。"""
        now = (time.perf_counter() - self._t0) * 1000
        start = self._open.pop(name)
        self.phases.append(Phase(name, start, now - start, kind))

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000


# 本仓库实测比例（demo_latency.py 的同一组数）
PLAN = [
    ("意图识别", 120, "pre"),
    ("查询改写", 260, "pre"),
    ("向量检索", 240, "pre"),
    ("BM25 检索", 80, "pre"),
    ("重排", 180, "pre"),
    ("模型首字", 640, "llm"),
    ("模型生成", 1880, "llm"),
]


def draw(wf: Waterfall, total: float) -> None:
    print(f"  {'阶段':<12}{'开始':>8}{'耗时':>9}{'占比':>7}  时间轴")
    print("  " + "-" * 66)
    scale = 40 / max(total, 1)
    for p in wf.phases:
        bar = " " * int(p.start_ms * scale) + "█" * max(1, int(p.dur_ms * scale))
        print(f"  {p.name:<12}{p.start_ms:>7.0f}ms{p.dur_ms:>8.0f}ms{p.dur_ms / total:>6.0%}  {bar}")
    print("  " + "-" * 66)
    print(f"  {'合计':<12}{'':>7}  {total:>7.0f}ms")


def main() -> None:
    wf = Waterfall()
    for name, dur, kind in PLAN:
        wf.start(name)
        time.sleep(dur / 1000)
        wf.end_at(name, kind)

    total = wf.total_ms
    ttft = next(p.start_ms + p.dur_ms for p in wf.phases if p.name == "模型首字")
    pre = sum(p.dur_ms for p in wf.phases if p.kind == "pre")
    gen = sum(p.dur_ms for p in wf.phases if p.kind == "llm")

    print("=" * 78)
    print("瀑布图：一次请求的时间轴")
    print("=" * 78)
    draw(wf, total)

    print("\n" + "=" * 78)
    print("★ 两个总时长，优化手法完全不同")
    print("=" * 78)
    print(f"  TTFT（首字）  {ttft:>7.0f} ms   用户从点击到看见第一个字")
    print(f"  整体（结束）  {total:>7.0f} ms   从点击到最后一行")
    print()
    print(f"  拆开：生成前（检索链路）{pre:.0f}ms，生成中 {gen:.0f}ms")
    print()
    print(f"  用户抱怨『点了没反应』 → 他在说前 {ttft:.0f}ms。")
    print(f"  用户抱怨『结果好久才完』 → 他在说后 {gen:.0f}ms。")

    print("\n" + "=" * 78)
    print("★ 按占比找可以砍的段")
    print("=" * 78)
    ranked = sorted(wf.phases, key=lambda p: -p.dur_ms)
    for i, p in enumerate(ranked[:4], 1):
        tag = {"pre": "影响 TTFT", "llm": "影响总时长（首字之后）", "post": "只影响总时长"}[p.kind]
        print(f"  第 {i} 慢：{p.name:<12}{p.dur_ms:>7.0f}ms ({p.dur_ms / total:>4.0%})  {tag}")
    print()
    print(f"  注意『模型生成』（{ranked[0].dur_ms:.0f}ms，占 {ranked[0].dur_ms / total:.0%}）是最长的一段，")
    print("  但优化它**不会让用户觉得变快** —— 因为它发生在首字之后。")
    print("  用户已经看到字在往外冒了，他的『等待焦虑』已经解除。")

    print("\n" + "=" * 78)
    print("三个可操作的结论")
    print("=" * 78)
    print("  1. 检索链路（880ms）全在 TTFT 里 —— 它是『点了没反应』的唯一来源")
    print("     → 并行化、流水线（step3 / step4）")
    print()
    print("  2. 模型生成（1880ms）只影响总时长")
    print("     → 减少输出长度、限制 max_tokens（但注意第 22 章：截断会引发重试）")
    print()
    print("  3. 首字 640ms 是模型自己的『思考时间』")
    print("     → 换更快的模型 / 减少 input（第 11 章）/ 用流式输出让用户先看到东西")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  先画瀑布图，再动手 —— 人对延迟的直觉几乎总是错的。")
    print("  下一步：把上面三段里『互不依赖』的部分并行起来。")


if __name__ == "__main__":
    main()
