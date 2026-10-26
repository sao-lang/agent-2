"""第 49 章 step3：ToolNode + tools_condition，手搭一个 Agent 图（离线）。

运行：
    python code/framework/lg/ch49/step3_tool_node.py

上一级的痛点：
    create_agent 一行就是一个 Agent，但它内部到底是什么？
    —— 其实就是这张图：model → (有 tool_calls?) → tools → model → ...

这一级做什么：
    ① 用 ToolNode + tools_condition 手搭一个等价于 create_agent 的图
    ② InjectedState / InjectedStore：让工具读到 state 和长期记忆
    ③ 对比：手搭 vs create_agent，各自适合什么

搭完你就能回答："框架报错时，它在哪一层？"
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.tools import InjectedToolArg, tool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lc"))

from _fake import ai, scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


@tool
def query_order(order_id: str) -> str:
    """按订单号查询订单状态。"""
    return f"{order_id}: 已签收 12 天，在保修期内"


@tool
def recall_user_pref(user_id: Annotated[str, InjectedToolArg()]) -> str:
    """读取用户偏好（user_id 由框架注入，模型看不到这个参数）。"""
    return f"用户 {user_id} 偏好：不要打电话，只用短信"


def main() -> None:
    line("① 手搭 Agent 图：4 个元素就够")
    class AgentState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]

    model = scripted(
        ai(tool_calls=[{"name": "query_order", "args": {"order_id": "A1201"}}]),
        ai("在保修期内，可以免费维修。"),
    )

    def call_model(state: AgentState) -> dict:
        return {"messages": [model.invoke(state["messages"])]}

    g = StateGraph(AgentState)
    g.add_node("model", call_model)
    g.add_node("tools", ToolNode([query_order]))
    g.add_edge(START, "model")
    g.add_conditional_edges("model", tools_condition)   # 有 tool_calls → "tools"，否则 → END
    g.add_edge("tools", "model")                        # 工具执行完回到模型
    agent = g.compile()

    out = agent.invoke({"messages": [HumanMessage("A1201 还能保吗")]})
    for m in out["messages"]:
        print(f"  {type(m).__name__:<14}{str(m.content)[:60]!r}")

    print("\n  → tools_condition 只做一件事：检查最后一条消息有没有 tool_calls")
    print("    有 → 返回 'tools'；没有 → 返回 END。就这么多。")

    line("② 和 create_agent 的等价性")
    from langchain.agents import create_agent

    m2 = scripted(
        ai(tool_calls=[{"name": "query_order", "args": {"order_id": "A1"}}]),
        ai("可以保。"),
    )
    quick = create_agent(m2, tools=[query_order])
    print(f"  手搭图节点 = {list(agent.get_graph().nodes)}")
    print(f"  create_agent 节点 = {list(quick.get_graph().nodes)}")
    print("  → 一模一样（create_agent 多了 state 扩展、中间件节点、checkpointer 支持）")

    line("③ InjectedToolArg：让工具拿到模型不该填的参数")
    print(f"  recall_user_pref 的 schema = {list(recall_user_pref.args)}")
    print("  → user_id 不在 schema 里，模型无法传；调用时必须由调用方补齐")
    try:
        recall_user_pref.invoke({})
    except Exception as e:  # noqa: BLE001
        print(f"  不补会怎样：{type(e).__name__}: {str(e)[:70]}")
    print(f"  补齐后：{recall_user_pref.invoke({'user_id': 'u1'})}")

    line("④ InjectedStore：工具直接读写长期记忆（第 28 章的分层存储）")
    print("""  from langgraph.store.memory import InMemoryStore
  from langgraph.prebuilt import InjectedStore

  @tool
  def save_pref(pref: str, store: Annotated[Any, InjectedStore()]) -> str:
      store.put(("user", "u1"), "pref", {"value": pref})
      return "已保存"

  → store 不进 prompt、不进 state，它是一份独立的 KV/向量存储。""")

    line("⑤ 手搭 vs create_agent：怎么选")
    print("""
  用 create_agent 当：
    · 标准「模型 + 工具」循环
    · 想直接用现成中间件（限流/摘要/审批/脱敏）
    · 需要 checkpointer / interrupt / 子图

  手搭图当：
    · 流程里有非 ReAct 的部分（先检索再生成再校验再重试）
    · 需要精确控制"哪一步能调哪个工具"
    · 需要 Send 做 map-reduce
    · 想彻底搞懂框架在干什么

  实战常见做法：外层手搭业务图，内层某个节点用 create_agent 当"任意 Agent"。
    """)


if __name__ == "__main__":
    main()
