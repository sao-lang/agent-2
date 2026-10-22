"""第 45 章 step3：你在别处看到的 0.x 写法，为什么现在不能照抄（离线）。

运行：
    python code/framework/lc/ch45/step3_legacy_vs_modern.py

上一级的痛点：
    网上 90% 的中文 LangChain 教程还是 0.x：
        from langchain.agents import initialize_agent
        from langchain.memory import ConversationBufferMemory
        from langchain.agents import AgentExecutor
    你在 1.x 里 import 这些会直接 ModuleNotFoundError。

这一级做什么：
    ① 逐条对照 0.x 写法 → 1.x 写法，并标注"它现在在哪"
    ② 手写一遍 0.x 的 AgentExecutor 循环 —— 看清 create_agent 替你做了什么
    ③ 把本章所有零件装成一个能跑的 Agent（带限流 + 错误兜底 + 记忆）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import ai, scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


@tool
def query_order(order_id: str) -> str:
    """按订单号查询订单状态。"""
    return f"{order_id}: 已签收 12 天，在保修期内"


@tool
def apply_refund(order_id: str, amount: float) -> str:
    """提交退款申请。用户明确要求退款时调用。"""
    return f"{order_id} 已提交退款 {amount} 元"


def main() -> None:
    line("① 0.x → 1.x 对照表（左边在 1.x 里已经 import 不到）")
    rows = [
        ("from langchain.agents import initialize_agent", "create_agent(model, tools=[...])"),
        ("AgentExecutor(agent=..., tools=...)",
         "create_agent(...) 返回的就是 CompiledStateGraph，直接 .invoke()"),
        ("agent_scratchpad 手工拼中间步骤", "框架自己维护 messages 列表"),
        ("ConversationBufferMemory / ConversationSummaryMemory", "checkpointer + SummarizationMiddleware"),
        ("from langchain.memory import *", "已移除；记忆 = 图状态"),
        ("from langchain.chains import LLMChain", "prompt | model | parser（LCEL）"),
        ("from langchain.chains import RetrievalQA", "自己组合 retriever | prompt | model"),
        ("create_stuff_documents_chain", "自己写 8 行拼上下文（见第 44 章 ④）"),
        ("langchain.agents.AgentType.OPENAI_FUNCTIONS", "不需要选类型，统一走 tool_calls"),
    ]
    for old, new in rows:
        print(f"  0.x  {old}")
        print(f"  1.x  → {new}\n")

    line("② 手写 AgentExecutor 的核心循环（15 行）")
    print("  create_agent 做的就是这件事，外加状态、断点、流式、中间件：\n")
    model = scripted(
        ai(tool_calls=[{"name": "query_order", "args": {"order_id": "A1201"}}]),
        ai("在保修期内，可以免费维修。"),
    )
    tools_by_name: dict[str, Any] = {"query_order": query_order}
    messages: list[Any] = [
        SystemMessage("你是售后助手。"),
        HumanMessage("A1201 还能保吗"),
    ]
    for step in range(1, 4):
        reply = model.invoke(messages)
        messages.append(reply)
        if not reply.tool_calls:
            print(f"  第 {step} 步：模型给出最终答案 → {reply.content!r}")
            break
        for call in reply.tool_calls:
            result = tools_by_name[call["name"]].invoke(call["args"])
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
            print(f"  第 {step} 步：调用 {call['name']}({call['args']}) → {result}")

    print("  → 这 15 行没有一个 import 来自框架。你现在能指出 create_agent 替你做了什么：")
    print("    · messages 的管理（自动追加 / 自动配对 tool_call_id）")
    print("    · 循环上限（不设置会死循环，见第 16 章）")
    print("    · 状态持久化（checkpointer）与中断（interrupt）")
    print("    · 中间件（限流/重试/摘要/审批/脱敏）")
    print("    · 流式（stream_mode）")

    line("③ 装成一个真正能用的 Agent")
    from langchain.agents import create_agent
    from langchain.agents.middleware import ModelCallLimitMiddleware, ToolErrorMiddleware

    def on_error(e: Exception, request: Any) -> str:  # noqa: ANN001, ARG001
        return f"工具失败：{type(e).__name__}。请告知用户稍后再试。"

    from langgraph.checkpoint.memory import InMemorySaver

    model2 = scripted(
        ai(tool_calls=[{"name": "apply_refund", "args": {"order_id": "A1201", "amount": 99}}]),
        ai("已提交退款 99 元。"),
        ai("你刚问的是 A1201 的退款，已提交。"),
    )
    agent = create_agent(
        model2,
        tools=[query_order, apply_refund],
        system_prompt="你是售后助手。退款前必须已经查到订单。",
        middleware=[ModelCallLimitMiddleware(run_limit=6), ToolErrorMiddleware(on_error=on_error)],
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "demo"}}
    r1 = agent.invoke({"messages": [HumanMessage("A1201 我要退款 99")]}, cfg)
    print(f"  第 1 轮 → {r1['messages'][-1].content!r}（共 {len(r1['messages'])} 条消息）")
    r2 = agent.invoke({"messages": [HumanMessage("我刚才问的哪一单？")]}, cfg)
    print(f"  第 2 轮 → {r2['messages'][-1].content!r}（共 {len(r2['messages'])} 条消息，含上轮）")

    line("④ 这一章留下的东西，在真实项目里的位置")
    print("""
  create_agent(model, tools, system_prompt, middleware, checkpointer, ...)
      ├── model            第 42 章（init_chat_model / 多 provider）
      ├── tools            第 44 章（@tool / MCP 转过来的 StructuredTool）
      ├── system_prompt    第 42 章（ChatPromptTemplate 的 system 部分）
      ├── middleware       第 45 章（限流/重试/摘要/审批/脱敏）
      └── checkpointer     第 47–49 章 + 第 26 章（记忆分层）
    """)


if __name__ == "__main__":
    main()
