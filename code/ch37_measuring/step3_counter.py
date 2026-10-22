"""第 57 章 step3：用一个计数器把"感觉贵"变成"知道贵"（离线）。

运行：
    python code/ch37_measuring/step3_counter.py

上一级的痛点：四个数字要手算，换个场景就得重算一遍。

这一级做什么：写一个 30 行的 `Counter`，用 `with` 包住调用，
自动记下"哪个环节、多少 token、多久、多少钱"，然后回答三个问题。

它和 `code/common/meter.py` 的区别：
  · 这里是最小骨架（只有 4 个字段，70 行），看清结构
  · `common/meter.py` 是它的增强版：加了 TTFT、重试计数、错误、导出、P95
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator
from contextlib import contextmanager

# 单价：元 / 百万 token。生产里从配置读，别写死（练习 2）
PRICE = {"in": 2.0, "out": 8.0}


@dataclass
class Rec:
    step: str
    input_tokens: int = 0
    output_tokens: int = 0
    ms: float = 0.0

    @property
    def cost(self) -> float:
        return self.input_tokens / 1e6 * PRICE["in"] + self.output_tokens / 1e6 * PRICE["out"]


@dataclass
class Counter:
    recs: list[Rec] = field(default_factory=list)

    @contextmanager
    def track(self, step: str) -> Iterator[Rec]:
        rec = Rec(step=step)
        t0 = time.perf_counter()
        try:
            yield rec
        finally:
            rec.ms = (time.perf_counter() - t0) * 1000
            self.recs.append(rec)

    def by_step(self) -> dict[str, tuple[int, float, float]]:
        """{环节: (调用次数, token 数, 成本)}"""
        out: dict[str, list[float]] = {}
        for r in self.recs:
            slot = out.setdefault(r.step, [0, 0, 0.0])
            slot[0] += 1
            slot[1] += r.input_tokens + r.output_tokens
            slot[2] += r.cost
        return {k: (int(v[0]), int(v[1]), v[2]) for k, v in out.items()}

    @property
    def total(self) -> float:
        return sum(r.cost for r in self.recs)


# 一次"客服 Agent"的调用链（数字仍是真实量级，不是编的）
RUN = [
    ("intent", 180, 30, 40),
    ("retrieve", 60, 0, 12),
    ("answer", 900, 600, 240),
    ("reflect", 1500, 120, 90),
]


def fake_call(step: str, tin: int, tout: int, ms: int) -> tuple[int, int]:
    """假装调了一次模型：睡 ms 毫秒，返回 (input, output)。"""
    time.sleep(ms / 1000)
    return tin, tout


def run_once(c: Counter) -> None:
    for step, tin, tout, ms in RUN:
        with c.track(step) as rec:
            rec.input_tokens, rec.output_tokens = fake_call(step, tin, tout, ms)


def main() -> None:
    c = Counter()
    run_once(c)
    run_once(c)          # 跑两次，看"次数"这一列

    print("=" * 70)
    print("① 按环节归因（跑了两遍）")
    print("=" * 70)
    print(f"  {'环节':<10}{'次数':>5}{'token':>8}{'成本(元)':>11}{'占比':>8}")
    print("  " + "-" * 42)
    for step, (n, t, cost) in sorted(c.by_step().items(), key=lambda kv: -kv[1][2]):
        print(f"  {step:<10}{n:>5}{t:>8}{cost:>11.6f}{cost / c.total:>8.1%}")
    print("  " + "-" * 42)
    print(f"  {'合计':<10}{len(c.recs):>5}{sum(r.input_tokens + r.output_tokens for r in c.recs):>8}"
          f"{c.total:>11.6f}{1.0:>8.0%}")

    print("\n" + "=" * 70)
    print("② 三个问题，2 秒答完")
    print("=" * 70)
    top = max(c.by_step().items(), key=lambda kv: kv[1][2])
    slow = max(c.recs, key=lambda r: r.ms)
    print(f"  哪一步最贵？      {top[0]}（{top[1][2] / c.total:.0%}）")
    print(f"  哪一步最慢？      {slow.step}（{slow.ms:.0f}ms，单次）")
    out_share = sum(r.output_tokens for r in c.recs) * PRICE["out"] / 1e6 / c.total
    print(f"  钱花在生成上多少？{out_share:.0%}（output 单价是 input 的 {PRICE['out'] / PRICE['in']:.0f} 倍）")

    print("\n" + "=" * 70)
    print("③ 一次改动，立刻能算出效果")
    print("=" * 70)
    before = c.total
    no_reflect = before - sum(r.cost for r in c.recs if r.step == "reflect")
    print(f"  现状（含反思）：        ¥{before / 2:.6f} / 次")
    print(f"  砍掉反思：              ¥{no_reflect / 2:.6f} / 次（省 {1 - no_reflect / before:.0%}）")
    print("  反思的收益见第 34 章：成功率 0/3 → 3/3，成本 ×2。")
    print("  → 所以'砍不砍'不是成本问题，是'你能接受多少错误率'的问题。")

    print("\n" + "=" * 70)
    print("结论：计数器本身不省一分钱")
    print("=" * 70)
    print("  它做的是让你**能算**：改一个参数之前先估、改完再测。")
    print("  没有它，所有'优化'都是猜；有了它，每次优化都能给一个数字。")
    print("\n  下一级：把它换成 common/meter.py（多了 TTFT、错误、重试、P95），")
    print("  然后跑一个真模型，看真实账单。")


if __name__ == "__main__":
    main()
