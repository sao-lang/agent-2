"""第 45 章 step1：create_agent 的全部参数与一次完整运行（离线）。

运行：
    python code/framework/lc/ch45/step1_create_agent.py

上一级的痛点：
    0.x 的 AgentExecutor + agent_scratchpad 需要你手写"把工具结果塞回提示词"。
    1.x 的 create_agent 直接返回一个**编译好的 LangGraph 图**，这些全替你做了。

这一级做什么：
    ① 最小 Agent：2 个工具 + 1 个剧本
    ② 把返回的图打印出来 —— 让你看见"Agent 就是一张图"
    ③ 逐个字段解释 create_agent 的参数
    ④ 一个坑：不传 checkpointer 就没有记忆（每次都是新会话）
"""
from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import ai, scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


@tool
def query_order(order_id: str) -> str:
    """按订单号查询订单状态。用户提供订单号时调用。"""
    return f"{order_id}: 已签收 12 天，在保修期内"


@tool
def apply_refund(order_id: str, amount: float) -> str:
    """提交退款。只在用户明确要求退款、且已确认订单号时调用。"""
    return f"已为 {order_id} 提交退款 {amount} 元，7 个工作日到账"


def main() -> None:
    line("① 最小 Agent：模型 + 工具 + 剧本")
    model = scripted(
        ai(tool_calls=[{"name": "query_order", "args": {"order_id": "A1201"}}]),
        ai(tool_calls=[{"name": "apply_refund", "args": {"order_id": "A1201", "amount": 99}}]),
        ai("已为你提交退款 99 元，7 个工作日到账。"),
    )
    from langchain.agents import create_agent

    agent = create_agent(model, tools=[query_order, apply_refund])
    print(f"  返回类型 = {type(agent).__name__}")
    print("  → 它不是一个「链」，而是一张编译好的状态图")

    out = agent.invoke({"messages": [HumanMessage("订单 A1201 坏了，我要退款")]})
    print("\n  完整消息序列：")
    for i, m in enumerate(out["messages"], 1):
        name = type(m).__name__
        if getattr(m, "tool_calls", None):
            body = " → ".join(f"{c['name']}{c['args']}" for c in m.tool_calls)
        else:
            body = repr(m.content)
        print(f"    {i}. {name:<13}{body}")

    line("② 这张图长什么样")
    try:
        print(agent.get_graph().draw_ascii())
    except Exception as e:  # noqa: BLE001
        # 画图依赖可选包 grandalf/pygraphviz；没装就直接读节点与边
        print(f"  （draw_ascii 需要额外依赖：{type(e).__name__}；改用节点/边列表）")
        g = agent.get_graph()
        print(f"  节点 = {list(g.nodes)}")
        print(f"  边   = {[(e.source, e.target) for e in g.edges]}")

    print("  图的节点只有两类：")
    print("    model     → 调模型，判断要不要调工具")
    print("    tools     → 执行工具，把结果写回 messages")
    print("  条件边：model 有 tool_calls 就去 tools，没有就去 END")

    line("③ create_agent 的参数逐个看")
    from langgraph.checkpoint.memory import InMemorySaver

    agent2 = create_agent(
        model,                                # str 或 BaseChatModel
        tools=[query_order, apply_refund],    # list[BaseTool | Callable | dict]
        system_prompt="你是售后助手，不确定时先查订单。",  # 等价于 system 消息
        middleware=[],                        # 中间件（下一级讲）
        response_format=None,                 # 结构化最终输出（Pydantic / TypedDict）
        state_schema=None,                    # 自定义 state（进阶）
        context_schema=None,                  # 运行时上下文类型
        checkpointer=InMemorySaver(),         # ★ 不传就没有记忆
        store=None,                           # 跨会话长期记忆
        interrupt_before=None,                # 人为在某个节点前停下（HITL）
        interrupt_after=None,
        debug=False,
        name="refund_agent",
        cache=None,
    )
    print(f"  带 checkpointer 的 agent 类型 = {type(agent2).__name__}")

    line("④ 一个坑：没有 checkpointer，就没有记忆")
    m1 = scripted("好的", "好的", "好的", "好的")
    no_mem = create_agent(m1, tools=[query_order])
    no_mem.invoke({"messages": [HumanMessage("我叫张三")]})
    out2 = no_mem.invoke({"messages": [HumanMessage("我叫什么？")]})
    print(f"  无 checkpointer → 返回 {len(out2['messages'])} 条消息（只剩本轮）")

    m2 = scripted("好的", "好的", "好的", "好的")
    with_mem = create_agent(m2, tools=[query_order], checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "u1"}}
    with_mem.invoke({"messages": [HumanMessage("我叫张三")]}, cfg)
    out3 = with_mem.invoke({"messages": [HumanMessage("我叫什么？")]}, cfg)
    print(f"  有 checkpointer → 返回 {len(out3['messages'])} 条消息（含上一轮）")
    print("  → 记忆不是「Agent 的功能」，是「checkpointer 的功能」，靠 thread_id 分区")

    line("⑤ 把 result 读干净：不要只看最后一条")
    print(f"  out['messages'][-1].content = {out['messages'][-1].content!r}")
    print(f"  中间还发生了什么 = {sum(1 for m in out['messages'] if type(m).__name__ == 'ToolMessage')} 次工具调用")
    print("  → 第 54 章会讲：trace 里必须能看到每一次调用和它的来源")


if __name__ == "__main__":
    main()
