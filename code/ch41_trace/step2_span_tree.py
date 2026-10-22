"""第 39 章 · 第 2 级：把卡片串成一棵树（理解 trace_id 和 parent_id）。

运行：
    python code/ch39_trace/step2_span_tree.py

这一级只加两个字段：
  · trace_id  ：这条记录属于哪"一次用户请求"（同一次请求的所有卡片用一个 id）
  · parent_id ：这条记录是谁的"子操作"（谁调用了它）

加完这两个字段，一堆散落的卡片就变成了一棵树。
"""
from __future__ import annotations

import time
import uuid


class Span:
    def __init__(self, name: str, parent: "Span | None" = None) -> None:
        self.name = name
        self.start = time.perf_counter()
        self.end: float | None = None
        self.result = ""
        self.span_id = uuid.uuid4().hex[:8]           # 自己是哪张卡片
        self.parent_id = parent.span_id if parent else None   # 谁生了我
        self.trace_id = parent.trace_id if parent else self.span_id  # 属于哪次请求

    def finish(self, result: str = "") -> "Span":
        self.end = time.perf_counter()
        self.result = result
        return self

    @property
    def duration_ms(self) -> float:
        return ((self.end or time.perf_counter()) - self.start) * 1000


# ---------------------------------------------------------------- 模拟一次 Agent 运行
# 注意：这里用"手动嵌套"的方式构造父子关系，先不引入任何框架。

spans: list[Span] = []

# 第 0 层：一次用户请求（根）
root = Span("用户请求：订单能退款吗")

# 第 1 层：三个步骤，父节点都是 root
plan = Span("步骤1 规划", parent=root)
time.sleep(0.02)
plan.finish("需要查退款政策")
spans += [plan]

act = Span("步骤2 执行", parent=root)
time.sleep(0.01)

# 第 2 层：act 下面挂了两次工具调用
tool1 = Span("工具 查退款政策", parent=act)
time.sleep(0.12)
tool1.finish("7 天内可退")
spans += [tool1]

tool2 = Span("工具 查订单状态", parent=act)
time.sleep(0.05)
tool2.finish("已签收 3 天")
spans += [tool2]

act.finish("拿到两条信息")
spans += [act]

answer = Span("步骤3 生成回答", parent=root)
time.sleep(0.08)
answer.finish("可以退款")
spans += [answer]

root.finish("完成")
spans.append(root)


# ---------------------------------------------------------------- 打印树
print("=" * 68)
print("① 所有卡片（平铺看，你已经看不出父子关系了）")
print("=" * 68)
print(f"  {'span_id':<10}{'parent':<10}{'name':<22}{'耗时':>8}")
for s in spans:
    print(f"  {s.span_id:<10}{str(s.parent_id or '-'):<10}{s.name:<22}{s.duration_ms:>7.0f}ms")

print("\n  👉 6 张卡片，你能说出'查订单'是谁调用的吗？能，但要一行行比对 id。")
print("     如果一次请求有 40 个 span，这就不可读了。")

print("\n" + "=" * 68)
print("② 按 parent_id 还原成树（这才是人看的形式）")
print("=" * 68)

children: dict[str | None, list[Span]] = {}
for s in spans:
    children.setdefault(s.parent_id, []).append(s)


def walk(parent_id: str | None, depth: int = 0) -> None:
    for s in sorted(children.get(parent_id, []), key=lambda x: x.start):
        print(f"  {'  ' * depth}{'└─ ' if depth else ''}{s.name:<24}{s.duration_ms:>7.0f}ms")
        walk(s.span_id, depth + 1)


walk(None)

print("\n" + "=" * 68)
print("③ 现在能一眼看出来的三件事")
print("=" * 68)
slowest = max([s for s in spans if s is not root], key=lambda s: s.duration_ms)
print(f"  1. 最慢的单步是：{slowest.name}（{slowest.duration_ms:.0f}ms）")
print("     最慢的是根节点本身是很正常的 —— 根节点的耗时 = 所有子步骤之和")
print(f"  2. 总耗时：{root.duration_ms:.0f}ms")
print("  3. 两次工具调用都在'步骤2 执行'下面 —— 这就是父子关系的价值：")
print("     它告诉你'这个工具调用属于哪一步推理'。")
print("\n  👉 到这里，你已经掌握了 span 和 trace 的全部核心：")
print("     span = 一张卡片；trace = 同一 trace_id 的所有卡片；")
print("     parent_id = 卡片之间的父子关系。")
print("     剩下的（自动记录、导出到文件、接平台）都是工程细节。")
