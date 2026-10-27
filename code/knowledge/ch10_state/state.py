"""State 的三个演进版本，以及两个分支并发写同一字段的丢与不丢。

不联网。用一个最小的状态对象与两个线程，把"覆盖"与"累加"的差别跑出来。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 版本 1：等于聊天记录

@dataclass
class V1:
    """把整段对话当状态。放什么全靠 messages。"""
    messages: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 版本 2：抽出任务字段

@dataclass
class V2:
    """把任务状态从 messages 里抽出来，字段固定。"""
    messages: list[dict] = field(default_factory=list)
    order_id: str | None = None
    eligible: bool | None = None
    reason: str | None = None


# ---------------------------------------------------------------- 版本 3：字段分三类

@dataclass
class V3:
    """字段分三类：输入（只写一次）、事实（只增）、结论（可覆盖）。"""
    messages: list[dict] = field(default_factory=list)

    user_intent: str = ""                  # 输入：本轮开始后不允许改
    facts: list[str] = field(default_factory=list)   # 事实：只增不减
    eligible: bool | None = None           # 结论：允许覆盖
    overwrites: int = 0

    def add_fact(self, fact: str) -> None:
        """append 是原子的（CPython），因此并发追加不丢。"""
        self.facts.append(fact)

    def set_conclusion(self, value: bool) -> None:
        self.eligible = value
        self.overwrites += 1


# ---------------------------------------------------------------- 并发写对照

def overwrite_demo() -> tuple[int, int]:
    """读-改-写：两个分支各读一次旧值，再写回，结果丢一次。"""
    state = {"count": 0}
    barrier = threading.Barrier(2)

    def branch() -> None:
        barrier.wait()                     # 让两个分支同时读到旧值
        current = state["count"]
        time.sleep(0.01)
        state["count"] = current + 1       # 两边都写 1

    ts = [threading.Thread(target=branch) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return state["count"], 2


def append_demo() -> tuple[int, int]:
    """累加式：各自 append，不读旧值，不丢。"""
    state: dict[str, list[str]] = {"facts": []}
    barrier = threading.Barrier(2)

    def branch(name: str) -> None:
        barrier.wait()
        time.sleep(0.01)
        state["facts"].append(name)

    ts = [threading.Thread(target=branch, args=(f"fact_{i}",)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return len(state["facts"]), 2


def main() -> None:
    got, expect = overwrite_demo()
    print(f"覆盖写：期望 {expect} 条，实际 {got} 条  {'丢了' if got < expect else '没丢'}")

    got, expect = append_demo()
    print(f"追加写：期望 {expect} 条，实际 {got} 条  {'丢了' if got < expect else '没丢'}")

    print()
    print("=== 版本 3 的一次写入 ===")
    s = V3(user_intent="A1001 能否退货")
    s.add_fact("订单已签收 3 天")
    s.add_fact("政策窗口 7 天")
    s.set_conclusion(True)
    s.set_conclusion(True)
    print(f"  facts={s.facts}")
    print(f"  eligible={s.eligible}  被覆盖 {s.overwrites} 次")
    print("  结论覆盖允许，覆盖次数被记下，用来发现'反复改主意'")


if __name__ == "__main__":
    main()
