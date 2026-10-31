"""LangGraph 的中断与恢复：编译时声明在哪一步前停下。

不联网。图有三步：读订单 -> 发退款 -> 记账。发退款这一步会改变外部世界，
所以 compile(interrupt_before=["refund"]) 让它在执行前停下，等人点头。

运行：python code/knowledge/ch37_langgraph_persist/interrupt_resume.py
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class Order(TypedDict):
    order_id: str
    log: Annotated[list[str], operator.add]


def read_order(state: Order) -> dict:
    return {"log": ["read_order"]}


def refund(state: Order) -> dict:
    return {"log": ["refund:已发起"]}


def bookkeeping(state: Order) -> dict:
    return {"log": ["bookkeeping"]}


def build():
    g = StateGraph(Order)
    g.add_node("read", read_order)
    g.add_node("refund", refund)
    g.add_node("book", bookkeeping)
    g.add_edge(START, "read")
    g.add_edge("read", "refund")
    g.add_edge("refund", "book")
    g.add_edge("book", END)
    return g.compile(
        checkpointer=InMemorySaver(),
        interrupt_before=["refund"],
    )


def main() -> None:
    app = build()
    thread = {"configurable": {"thread_id": "refund-A1001"}}

    print("=== 1. 第一次 invoke：停在 refund 之前 ===")
    out = app.invoke({"order_id": "A1001", "log": []}, thread)
    print(f"  返回：{out}")
    state = app.get_state(thread)
    print(f"  next={state.next}  log={state.values['log']}")
    print("  <- 进程可以退出；检查点里有 order_id，恢复时不需要客户端再传一遍")
    print()

    print("=== 2. 人工审批：读状态、写决定 ===")
    print(f"  审批卡片：order_id={state.values['order_id']}，下一步={state.next}")
    approved = True
    if not approved:
        print("  拒绝：不恢复，把 thread 标记为 cancelled")
        return
    print("  通过：调用 invoke(None, 同一 config) 从检查点继续")
    print()

    print("=== 3. 恢复执行 ===")
    out = app.invoke(None, thread)
    print(f"  返回：{out}")
    print(f"  最终 log={app.get_state(thread).values['log']}")
    print()
    print("=== 4. 重复恢复会怎样 ===")
    out2 = app.invoke(None, thread)
    print(f"  再次 invoke(None)：{out2}")
    print("  <- 已在 END，恢复是空操作；refund 不会被执行两次")
    print("     这是 checkpoint 与幂等键的分工：前者保证不重跑，后者保证重跑也不重复副作用")


if __name__ == "__main__":
    main()
