"""第 2 章 · 第 1 级：10 行看懂"span 是什么"。

运行：
    python code/ch02_trace/step1_what_is_span.py

这个文件只有一个目的：让你**看见** span 长什么样。
不要纠结写法好不好，先记住"一张卡片有 5 个字段"。
"""
from __future__ import annotations

import time

print("=" * 60)
print("① 手工记录一次操作 —— 这就是 span 的全部内容")
print("=" * 60)

# ---- 一个 span 就是"一张卡片"，记录一次操作的 5 件事 ----
start = time.perf_counter()          # ① 什么时候开始
name = "查询订单"                     # ② 做的是什么事
time.sleep(0.12)                     # （假装这里在查数据库）
result = "订单 A12345 已发货"          # ③ 结果是什么
end = time.perf_counter()            # ④ 什么时候结束
duration_ms = (end - start) * 1000   # ⑤ 花了多久

print(f"  名称   : {name}")
print(f"  耗时   : {duration_ms:.0f} ms")
print(f"  结果   : {result}")
print(f"  开始   : {start:.6f}（相对进程启动的秒数）")
print(f"  结束   : {end:.6f}")


print("\n" + "=" * 60)
print("② 把它写成一个类 —— 这样就能复用")
print("=" * 60)


class Span:
    """一张"操作记录卡"。

    真实系统里还会有 trace_id / span_id / parent_id / 属性，
    但先记住这 5 个字段就够了。
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.start = time.perf_counter()
        self.end: float | None = None
        self.result = ""

    def finish(self, result: str) -> None:
        self.end = time.perf_counter()
        self.result = result

    @property
    def duration_ms(self) -> float:
        end = self.end or time.perf_counter()
        return (end - self.start) * 1000

    def __str__(self) -> str:
        return f"[{self.name}] {self.duration_ms:.0f}ms → {self.result}"


span = Span("查询订单")
time.sleep(0.12)
span.finish("订单 A12345 已发货")
print(f"  {span}")


print("\n" + "=" * 60)
print("③ 记录两次操作 —— 你马上会发现一个问题")
print("=" * 60)

s1 = Span("查询订单")
time.sleep(0.10)
s1.finish("已发货")

s2 = Span("生成回复")
time.sleep(0.05)
s2.finish("您的订单已发货")

for s in (s1, s2):
    print(f"  {s}")

print("\n  问：这两次操作，谁先谁后？")
print("     两次都是'生成回复'慢，还是'查询'慢？")
print("     如果中间还有 10 次操作，你怎么一眼看出它们的关系？")
print("\n  👉 光有'卡片'不够，还需要'把卡片串起来的线'。")
print("     那根线叫 trace_id，卡片之间的上下级关系叫 parent_id。")
print("     下一级（step2_span_tree.py）就让它们串起来。")
