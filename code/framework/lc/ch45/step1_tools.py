"""第 45 章 step1：@tool 的完整写法与四个进阶点（离线）。

运行：
    python code/framework/lc/ch45/step1_tools.py

上一级的痛点：
    你写了一堆普通函数，模型看不到它们 —— 模型只能看到"工具清单"。
    @tool 就是"把函数变成模型能看见的、带 schema 的工具"。

这一级做什么：
    ① 最简 @tool（docstring 就是 description）
    ② args_schema：参数描述写清楚，模型才选得对
    ③ ToolException + handle_tool_error：工具出错怎么变成"给模型看的反馈"
    ④ response_format="content_and_artifact"：既要给模型看摘要，又要留下原始数据
    ⑤ InjectedToolCallId / InjectedState：把"运行时信息"偷偷塞给工具
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage
from langchain_core.tools import InjectedToolCallId, ToolException, tool
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import ai, scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① 最简 @tool：函数签名 + docstring 就是全部")
    @tool
    def get_weather(city: str) -> str:
        """查询指定城市的天气。用户在问冷热、下雨、要不要带伞时用。"""
        return f"{city}：晴，22℃"

    print(f"  name        = {get_weather.name}")
    print(f"  description = {get_weather.description}")
    print(f"  args        = {get_weather.args}")
    print(f"  调用        = {get_weather.invoke({'city': '北京'})}")

    line("② args_schema：参数语义写清楚，模型才不会乱填")
    class RefundArgs(BaseModel):
        order_id: str = Field(description="订单号，形如 A1201")
        reason: Literal["质量问题", "七天无理由", "发错货"] = Field(description="退款原因")
        amount: float = Field(gt=0, description="退款金额（元）")

    @tool(args_schema=RefundArgs)
    def apply_refund(order_id: str, reason: str, amount: float) -> str:
        """提交退款申请。只在用户明确要求退款时调用。"""
        return f"已提交：{order_id} / {reason} / {amount} 元"

    print(f"  json schema 的 properties = {list(apply_refund.args_schema.model_json_schema()['properties'])}")
    print(f"  参数说明会一起喂给模型：{RefundArgs.model_fields['reason'].description}")
    print(f"  调用 = {apply_refund.invoke({'order_id': 'A1201', 'reason': '质量问题', 'amount': 99})}")

    line("③ ToolException：工具内部错误 → 转成给模型看的自然语言")
    @tool
    def query_order(order_id: str) -> str:
        """按订单号查询订单状态。"""
        raise ToolException("订单不存在：check_order_id 校验失败")

    print("  handle_tool_error 未设置时 → 直接抛：", end="")
    try:
        query_order.invoke({"order_id": "X"})
    except ToolException as e:
        print(type(e).__name__)

    query_order.handle_tool_error = "订单号可能有误，请让用户确认后重试"
    print(f"  设置 handle_tool_error 后 → 返回文本：{query_order.invoke({'order_id': 'X'})!r}")
    print("  → 模型看到的是这句话，它会自己决定「再问用户」还是「换个参数」")

    line("④ content_and_artifact：给模型摘要，给程序原始数据")
    @tool(response_format="content_and_artifact")
    def search_kb(query: str):
        """在知识库中检索。"""
        docs = [{"id": 1, "text": "退货需在 30 天内", "score": 0.91},
                {"id": 2, "text": "退款 7 个工作日到账", "score": 0.84}]
        return "找到 2 条：退货需在 30 天内；退款 7 个工作日到账", docs

    res = search_kb.invoke({"query": "退货"})
    print(f"  Tool.invoke 返回 = {type(res).__name__}: {str(res)[:70]}")
    # artifact 只在「进入 Agent 后的 ToolMessage」上才保留：
    msg = search_kb.invoke(
        {"type": "tool_call", "id": "c1", "name": "search_kb", "args": {"query": "退货"}}
    )
    print(f"  以 tool_call 方式调用 → {type(msg).__name__}")
    print(f"  msg.content（模型看的）  = {msg.content}")
    print(f"  msg.artifact（程序留的） = {msg.artifact}")
    print("  → 前端要显示引用来源时，读 artifact；别再让模型把 id 抄一遍")

    line("⑤ InjectedToolCallId：工具要回写消息时，需要知道自己的 call_id")
    @tool
    def update_todo(item: str, tool_call_id: str = InjectedToolCallId()) -> str:  # noqa: ANN001
        """更新待办清单。"""
        return f"已记录 {item}（call_id={tool_call_id}）"

    print(f"  args（注意 tool_call_id 不出现在 schema 里）= {list(update_todo.args)}")
    print("  → 注入参数不暴露给模型，由框架在调用时自动填")

    line("⑥ 工具清单真的会被模型看见吗——看一次真实调用")
    @tool
    def add(a: int, b: int) -> int:
        """两数相加"""
        return a + b

    fake = scripted(
        ai(tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}}]),
        ai("结果是 5"),
    )
    from langchain.agents import create_agent

    agent = create_agent(fake, tools=[add])
    out = agent.invoke({"messages": [HumanMessage("2+3=?")]})
    for m in out["messages"]:
        name = type(m).__name__
        extra = f" calls={m.tool_calls}" if getattr(m, "tool_calls", None) else ""
        print(f"  {name:<14}{m.content!r}{extra}")


if __name__ == "__main__":
    main()
