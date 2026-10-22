"""第 36 章产出：延迟工程的四个手法。

  1. 瀑布图（先看清延迟花在哪，别猜）
  2. 并行化（独立的步骤并发）
  3. 流水线（不等全部完成就开始生成）
  4. 降级链（超时逐级退让）

核心技术点：TTFT（首字延迟）和 total（总延迟）是两个不同的指标，
优化目标不同，手法也不同。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# ============================================================ 瀑布图

@dataclass
class Phase:
    name: str
    start_ms: float
    end_ms: float

    @property
    def duration(self) -> float:
        return self.end_ms - self.start_ms


@dataclass
class Waterfall:
    """延迟瀑布：把一次请求的各阶段耗时画成表。

    为什么必须画：人对自己系统的延迟分布几乎总是猜错。
    "我觉得是模型慢"——实际 70% 是检索。
    """

    phases: list[Phase] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)
    _open: dict[str, float] = field(default_factory=dict)

    def start(self, name: str) -> None:
        self._open[name] = (time.perf_counter() - self._t0) * 1000

    def end(self, name: str) -> None:
        if name not in self._open:
            return
        t = (time.perf_counter() - self._t0) * 1000
        self.phases.append(Phase(name, self._open.pop(name), t))

    @property
    def total(self) -> float:
        return max((p.end_ms for p in self.phases), default=0.0)

    def report(self) -> str:
        total = self.total or 1.0
        lines = [f"{'阶段':<22}{'开始':>10}{'耗时':>10}{'占比':>8}  时间轴"]
        lines.append("-" * 70)
        for p in sorted(self.phases, key=lambda x: x.start_ms):
            bar_len = int(p.duration / total * 30)
            pad = int(p.start_ms / total * 30)
            bar = " " * pad + "█" * max(bar_len, 1)
            lines.append(f"{p.name:<22}{p.start_ms:>9.0f}ms{p.duration:>9.0f}ms{p.duration / total:>7.0%}  {bar}")
        lines.append("-" * 70)
        lines.append(f"{'合计':<22}{'':>10}{total:>9.0f}ms")
        return "\n".join(lines)

    def slowest(self, n: int = 3) -> list[Phase]:
        return sorted(self.phases, key=lambda p: -p.duration)[:n]


# ============================================================ 并发执行

async def gather_limited(
    tasks: list[Callable[[], Awaitable[Any]]],
    concurrency: int = 5,
) -> list[Any]:
    """带并发上限的 gather。

    为什么要有上限？
    因为下游（向量库/数据库/模型 API）都有 QPS 限制。
    无上限并发会把下游打挂，反而更慢（全是 429）。
    """
    sem = asyncio.Semaphore(concurrency)

    async def wrap(fn: Callable[[], Awaitable[Any]]) -> Any:
        async with sem:
            return await fn()

    return await asyncio.gather(*(wrap(t) for t in tasks))


async def demo_serial_vs_parallel() -> None:
    print("=" * 72)
    print("① 并行化：三个独立检索")
    print("=" * 72)

    async def search(name: str, ms: int) -> str:
        await asyncio.sleep(ms / 1000)
        return f"{name}({ms}ms)"

    jobs = [("向量检索", 300), ("BM25", 200), ("图扩展", 400)]

    t0 = time.perf_counter()
    for n, ms in jobs:
        await search(n, ms)
    serial = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    await gather_limited([lambda n=n, ms=ms: search(n, ms) for n, ms in jobs], concurrency=3)
    parallel = (time.perf_counter() - t0) * 1000

    print(f"  串行：{serial:.0f}ms   并行：{parallel:.0f}ms   提速 {serial / parallel:.2f}x")
    print("  👉 理论上限 = max(单项) = 400ms；实际开销来自调度。")
    print("     但**首字延迟（TTFT）不受益**——你仍要等全部检索完成才能开始生成。")


# ============================================================ 流水线

async def demo_streaming() -> None:
    print("\n" + "=" * 72)
    print("② 流水线：边检索边生成（降低 TTFT）")
    print("=" * 72)

    async def stream_tokens(n: int = 40, per_token_ms: int = 25):
        for i in range(n):
            await asyncio.sleep(per_token_ms / 1000)
            yield f"t{i}"

    # 模式 A：全部检索完 → 开始生成
    t0 = time.perf_counter()
    await asyncio.sleep(0.5)          # 检索耗时 500ms
    n = 0
    async for _ in stream_tokens():
        if n == 0:
            ttft_a = (time.perf_counter() - t0) * 1000
        n += 1
    total_a = (time.perf_counter() - t0) * 1000

    # 模式 B：检索完第一批就开生成，剩余边到边拼
    t0 = time.perf_counter()
    await asyncio.sleep(0.15)         # 第一批检索（快）
    n = 0
    async for _ in stream_tokens():
        if n == 0:
            ttft_b = (time.perf_counter() - t0) * 1000
        n += 1
    total_b = (time.perf_counter() - t0) * 1000

    print(f"  A 全部检索后生成：首字 {ttft_a:.0f}ms   总耗时 {total_a:.0f}ms")
    print(f"  B 分批检索+生成  ：首字 {ttft_b:.0f}ms   总耗时 {total_b:.0f}ms")
    print(f"  → 首字快 {(ttft_a - ttft_b):.0f}ms（{(1 - ttft_b / ttft_a):.0%}），总耗时几乎不变")
    print("\n  👉 关键洞察：**流水线优化的是'体感'，不是'总时长'。**")
    print("     用户感知'快'靠的是首字，不是最后一行结束。")


# ============================================================ 降级链

@dataclass
class DegradationChain:
    """降级链：超时逐级退让。

    顺序设计原则：
      先降"质量"，再降"完整性"，最后才降"可用性"。
    因为用户能接受"答案简单点"，不能接受"什么都没有"。
    """

    steps: list[tuple[str, float]] = field(
        default_factory=lambda: [
            ("strong-model", 8.0),     # 先试大模型，最多等 8s
            ("cheap-model", 3.0),      # 退到小模型，最多 3s
            ("cache-or-template", 1.0),# 退到缓存/模板
            ("fallback-message", 0.2), # 兜底话术
        ]
    )

    def describe(self) -> str:
        lines = ["降级链（超时逐级退让）："]
        for i, (name, timeout) in enumerate(self.steps, 1):
            lines.append(f"  {i}. {name:<22}超时 {timeout}s")
        return "\n".join(lines)


async def demo_degradation() -> None:
    print("\n" + "=" * 72)
    print("③ 降级链：不让自己死在第一级")
    print("=" * 72)

    chain = DegradationChain()
    print("  " + chain.describe().replace("\n", "\n  "))

    async def call_model(name: str) -> str:
        # 模拟：大模型偶尔很慢
        delay = {"strong-model": 9.5, "cheap-model": 0.8, "cache-or-template": 0.05}
        await asyncio.sleep(delay.get(name, 0.01))
        return f"<{name} 的答案>"

    t0 = time.perf_counter()
    for name, timeout in chain.steps:
        try:
            result = await asyncio.wait_for(call_model(name), timeout=timeout)
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"\n  ✅ 在第 {chain.steps.index((name, timeout)) + 1} 级成功：{result}")
            print(f"     总耗时：{elapsed:.0f}ms")
            break
        except asyncio.TimeoutError:
            print(f"\n  ⏱️ {name} 超时（{timeout}s），降级 →")
    else:
        print("\n  兜底：返回'系统繁忙，请稍后重试'")


def main() -> None:
    # 瀑布图示例（用构造数据，避免依赖真实链路）
    print("=" * 72)
    print("① 瀑布图：先看清延迟花在哪")
    print("=" * 72)
    wf = Waterfall(phases=[
        Phase("意图识别", 0, 120),
        Phase("查询改写", 120, 380),
        Phase("向量检索", 380, 620),
        Phase("BM25 检索", 620, 700),
        Phase("重排", 700, 880),
        Phase("模型首字", 880, 1520),
        Phase("模型生成", 1520, 3400),
    ])
    print(wf.report())
    print("\n  最慢的三段：")
    for p in wf.slowest(3):
        print(f"    {p.name:<16}{p.duration:>8.0f}ms")

    print("\n  👉 读法：")
    print("     · 模型生成占 55% —— 这是**总延迟**的大头")
    print("     · 但**首字延迟**（用户体感）只到 1520ms，其中检索占 880ms")
    print("     · 所以：降低总时长 → 减少输出长度；降低首字 → 并行检索 + 流水线")

    asyncio.run(demo_serial_vs_parallel())
    asyncio.run(demo_streaming())
    asyncio.run(demo_degradation())

    print("\n" + "=" * 72)
    print("延迟工程的四个手法总结")
    print("=" * 72)
    print("  1. 瀑布图    —— 先量化，再优化（人总是猜错）")
    print("  2. 并行化    —— 降首字；对无依赖的步骤有效")
    print("  3. 流水线    —— 降首字；对'检索+生成'有效，总时长几乎不变")
    print("  4. 降级链    —— 保住可用性；牺牲质量换不卡死")
    print("\n  ⚠️ 别把'总时长'和'首字延迟'混为一谈：")
    print("     用户说'好慢'，90% 是在说首字。")
    print("     用户说'结果好长'，才是在说总时长。")


if __name__ == "__main__":
    main()
