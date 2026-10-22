"""第 50 章 step2：持久化、HITL 中断与时间回溯（离线）。

运行：
    python code/framework/lg/ch50/step2_persist_hitl.py

上一级的痛点：
    Agent 跑到第 3 步要人审批，进程一重启就全丢了；
    用户说"刚才那版不对"，你没法回到两步前重跑。

这一级做什么：
    ① checkpointer + thread_id：同一个会话能续上
    ② interrupt()：在危险动作前停下，等人工决定（批准 / 修改 / 拒绝）
    ③ Command(resume=...)：带着人的决定继续跑
    ④ get_state_history + 回到某个 checkpoint 重跑（时间回溯）
    ⑤ 一个坑：interrupt 之前的副作用不能重复执行（幂等）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

sys.path.insert(0, str(Path(__file__).parent))


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


class S(TypedDict):
    messages: Annotated[list, add_messages]
    amount: int
    status: str
    log: Annotated[list[str], lambda a, b: a + b]


def draft(state: S) -> dict:
    return {"amount": 99, "status": "drafted", "log": ["draft"]}


def approve(state: S) -> Command:
    # interrupt() 会**暂停整个图**，把 payload 交给外部；resume 时返回值就是人的决定
    decision = interrupt({"question": f"是否批准退款 {state['amount']} 元？", "order": "A1201"})
    if decision == "yes":
        return Command(goto="execute", update={"status": "approved", "log": ["approve:yes"]})
    return Command(goto=END, update={"status": "rejected", "log": ["approve:no"]})


def execute(state: S) -> dict:
    return {"status": "done", "log": ["execute"]}


def main() -> None:
    line("① 先看不带 checkpointer 会怎样")
    def build(with_mem: bool):
        g = StateGraph(S)
        g.add_node("draft", draft)
        g.add_node("approve", approve)
        g.add_node("execute", execute)
        g.add_edge(START, "draft")
        g.add_edge("draft", "approve")
        g.add_edge("execute", END)
        return g.compile(checkpointer=InMemorySaver() if with_mem else None)

    plain = build(False)
    out0 = plain.invoke({"messages": [], "amount": 0, "status": "", "log": []})
    print(f"  不带 checkpointer 时 invoke 返回：__interrupt__ 存在 = {bool(out0.get('__interrupt__'))}")
    print("  → 看起来「停住了」，但状态没地方存")
    try:
        plain.invoke(Command(resume="yes"), {"configurable": {"thread_id": "x"}})
    except Exception as e:  # noqa: BLE001
        print(f"  想继续时 → {type(e).__name__}: {e}")

    line("② 带 checkpointer：interrupt 会「停住」，并把控制权交还给你")
    app = build(True)
    cfg = {"configurable": {"thread_id": "u1-order-A1201"}}
    out = app.invoke({"messages": [HumanMessage("我要退款")], "amount": 0, "status": "", "log": []}, cfg)
    interrupts = out.get("__interrupt__", [])
    print(f"  返回里有 __interrupt__：{bool(interrupts)}")
    if interrupts:
        print(f"  人看到的问题 = {interrupts[0].value}")
    snap = app.get_state(cfg)
    print(f"  当前状态 = next={snap.next}, status={snap.values['status']}")
    print("  → 进程此刻可以**退出**。状态已经写进 checkpointer，下次接着跑。")

    line("③ 人的决定通过 Command(resume=...) 送回去")
    out2 = app.invoke(Command(resume="yes"), cfg)
    print(f"  继续跑完 → status={out2['status']}, log={out2['log']}")

    print("\n  三种人工动作：")
    print("    resume='yes'        → 批准，继续")
    print("    resume='no'         → 拒绝，走另一条分支（或 END）")
    print("    resume={'amount': 50} → 修改参数后继续（你的图要能接受 dict）")

    line("④ 时间回溯：get_state_history + 回到某一步")
    history = list(app.get_state_history(cfg))
    print(f"  共 {len(history)} 个 checkpoint：")
    for i, h in enumerate(history):
        n = h.next
        print(f"    {i}. step={h.metadata.get('step')} next={n} status={h.values.get('status')!r}")

    # 找到 approve 之前那个快照（next == ('approve',)）
    target = next((h for h in history if h.next == ("approve",)), None)
    if target:
        print(f"\n  找到 approve 之前的快照：checkpoint_id={target.config['configurable']['checkpoint_id'][:8]}…")
        print("  用法 A：从它 fork 出一个新分支（不覆盖原历史）")
        print("     app.invoke(None, {**cfg, 'configurable': {'checkpoint_id': target.config['configurable']['checkpoint_id']}})")
        print("  用法 B：update_state 改一个字段后重跑")
        print("     app.update_state(target.config, {'amount': 50})")

        forked = app.invoke(
            Command(resume="no"),
            {**cfg, "configurable": {**cfg["configurable"],
                                      "checkpoint_id": target.config["configurable"]["checkpoint_id"]}},
        )
        print(f"\n  在旧快照上 resume='no' → status={forked['status']}（走了拒绝分支）")

    line("⑤ 一个坑：interrupt 之前的副作用会重跑")
    print("""
  你的图如果是这样：

      charge_card  →  interrupt(等审批)  →  ship

  那么"从 checkpoint 回溯重跑"时会**再次执行 charge_card**。
  真实项目三条防线：
    1. 把有副作用的动作放在 interrupt **之后**
    2. 幂等键：charge_card(order_id, idempotency_key=f"{thread_id}:{step}")
    3. 副作用节点自己查一次"做过没有"（读 DB，不读 state）
    """)

    line("⑥ Durable 级别：什么时候写盘")
    print("""  compile(checkpointer=..., ) 之外还有 durability 参数：
    "exit"    只在图跑完/中断时写（最快，崩溃会丢当前轮）
    "async"   每步异步写（默认，好平衡）
    "sync"    每步同步写完再继续（最稳，最慢）
  → Agent 有长任务时用 "sync"；只是聊天用 "async"。""")


if __name__ == "__main__":
    main()
