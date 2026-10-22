"""第 45 章 step3：记忆为什么迁到 LangGraph，以及 MCP 的两侧（离线）。

运行：
    python code/framework/lc/ch45/step3_memory_mcp.py

上一级的痛点：
    · 0.x 有 ConversationBufferMemory 等一堆 Memory 类，1.x 全没了
    · MCP 到底是"另一个工具格式"还是"另一层协议"？和 @tool 什么关系？

这一级做什么：
    ① 手写"记忆"的三种做法，看清 Memory 类只是包装
    ② 说明为什么 1.x 把记忆交给 LangGraph 的 checkpointer
    ③ MCP 的 client / server 两侧最小模型：tools/list → 转成 LangChain 工具
    ④ 安全边界：allowed-tools 收窄 + 工具来源前缀
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool, tool

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① 手写记忆：三种做法，代价完全不同")
    llm = scripted(*(["好的"] * 10))

    # 做法 A：全量保留（最准，最贵）
    history_a: list[BaseMessage] = []
    for q in ["我叫张三", "我上周买的耳机", "我要退货"]:
        history_a.append(HumanMessage(q))
        history_a.append(llm.invoke(history_a))
    print(f"  A 全量保留     : {len(history_a)} 条消息，越长越贵")

    # 做法 B：只留最近 N 轮（便宜，丢信息）
    history_b: list[BaseMessage] = []
    for q in ["我叫张三", "我上周买的耳机", "我要退货"]:
        history_b.append(HumanMessage(q))
        history_b.append(llm.invoke(history_b))
        history_b = history_b[-4:]
    print(f"  B 只留最近 2 轮 : {len(history_b)} 条消息，用户名字已经丢了")

    # 做法 C：摘要 + 最近 N 轮
    summary = "用户自称张三，上周买了耳机。"
    history_c = [HumanMessage("我要退货")]
    print(f"  C 摘要 + 最近轮 : 摘要 {len(summary)} 字 + {len(history_c)} 条消息")

    print("\n  → 三种做法的代码都只有十行。ConversationBufferMemory 干的就是 A 那一小段。")

    line("② 为什么 1.x 把记忆交给 LangGraph")
    print("  记忆的三个真问题，Memory 类回答不了：")
    print("    1. 存在哪？     进程内存 → 重启全丢（LangGraph: checkpointer = SQLite/PG）")
    print("    2. 按什么粒度？ 一轮 / 一个会话 / 一个用户（LangGraph: thread_id + namespace）")
    print("    3. 怎么裁剪？   全量 / 窗口 / 摘要（LangGraph: 中间件 SummarizationMiddleware）")
    print("  → 换句话说：记忆的本质是「状态管理」，不是「消息容器」。状态应该由运行时管。")
    print("  → 第 47–49 章会用它：create_agent(..., checkpointer=InMemorySaver())")

    line("③ MCP：协议两边各做什么")
    print("""
  server 侧（提供能力的人）                        client 侧（用能力的人）
  ─────────────────────────────                   ─────────────────────────────
  @mcp.tool() 定义函数                            连接：stdio / http(sse)
  tools/list 返回 名称+描述+inputSchema            tools/list 拿到清单
  tools/call 执行并返回文本                        tools/call 发参数、收结果
                                                   → 转成 LangChain 的 StructuredTool
    """)
    # 模拟一条 tools/list 返回
    mcp_listing = [
        {
            "name": "query_order_status",
            "description": "查询订单状态",
            "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
        }
    ]

    def to_langchain(server: str, spec: dict[str, Any]):
        """真实项目里这一步用 langchain-mcp-adapters 的 load_mcp_tools()，
        它做的事和下面一样：把 inputSchema 变成 args_schema，把调用转发成 tools/call。"""
        from pydantic import create_model

        schema = spec["inputSchema"]
        fields = {
            k: (str, ...) for k in schema.get("required", [])
        }
        args_model = create_model(f"{spec['name']}_args", **fields)

        def _call(**kwargs: Any) -> str:
            return f"[{server}] tools/call {spec['name']} -> {kwargs}"

        return StructuredTool.from_function(
            func=_call,
            name=f"{server}__{spec['name']}",
            description=spec["description"],
            args_schema=args_model,
        )

    tools = [to_langchain("order-mcp", s) for s in mcp_listing]
    print(f"  tools/list 1 条 → 转成 LangChain 工具：{[t.name for t in tools]}")
    print(f"  调用：{tools[0].invoke({'order_id': 'A1201'})}")
    print("\n  → MCP 不是「另一种工具格式」，而是「工具发现 + 调用」的标准协议。")
    print("    转换后它就是普通 Tool，Agent 完全不知道它来自网络。")

    line("④ 安全边界：MCP 工具是别人写的")
    print("  三条硬约束（第 33 章沙箱 / 第 55 章 Guard 的落地）：")
    print("    1. 名字加服务前缀    order-mcp__query_order  （出事能定位到服务）")
    print("    2. allowed-tools 收窄 skill 能看到的工具集合")
    print("    3. 危险动作默认拦    delete / drop / truncate 一律人工审批")
    print("\n  反例：某 MCP 服务升级后新增了 delete_all_orders，")
    print("        你的 agent 第二天就把表清了 —— 因为你没做第 3 条。")

    line("⑤ 把这三种能力接起来的形状")
    @tool
    def search_kb(query: str) -> str:
        """检索知识库"""
        return "退货需在 30 天内申请"

    print("  第 45 章留下的零件：")
    print(f"    tools      : @tool 定义的 {len(tools) + 1} 个（本地 + MCP）")
    print("    retriever  : VectorStore.as_retriever()（也可包成 Tool 给 Agent 用）")
    print("    memory     : 交给 checkpointer（下一部分）")
    print("    agent      : create_agent(model, tools=[...], middleware=[...])  ← 第 46 章")


if __name__ == "__main__":
    main()
