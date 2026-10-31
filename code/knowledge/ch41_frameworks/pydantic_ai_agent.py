"""第 41 章 · pydantic-ai：类型化输出、工具、依赖与重试。

运行：
    $env:PYTHONPATH="$PWD\\.libs"; $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch41_frameworks/pydantic_ai_agent.py

不联网、不需要 key：模型用 pydantic-ai 自带的 FunctionModel 接一段剧本，
剧本返回的 JSON 是固定的。这里要看的是框架替掉了哪几段手写代码：
输出结构校验、工具调用循环、校验失败重试、依赖注入。
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

ORDERS = {"A1001": {"signed_days_ago": 3, "unopened": True, "price": 199}}


class RefundDecision(BaseModel):
    """输出结构。字段约束写在类型上，校验失败由框架负责重试。"""

    eligible: bool = Field(description="是否符合退货条件")
    reason: str = Field(max_length=40, description="不超过 40 字的理由")
    days_left: int = Field(ge=0, description="距签收满十五天还剩几天")


def lookup_order(ctx: RunContext[dict], order_id: str) -> str:
    """查订单状态：签收天数、是否拆封、金额。"""
    order = ctx.deps[order_id]
    return f"签收 {order['signed_days_ago']} 天，未拆封={order['unopened']}，金额 {order['price']} 元"


def scripted(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """剧本：先调工具，拿到结果后给结构化输出。"""
    has_tool_return = any(
        getattr(part, "part_kind", "") == "tool-return"
        for message in messages
        for part in getattr(message, "parts", [])
    )
    print(f"  模型收到 {len(messages)} 条消息，已有工具结果={has_tool_return}")
    if not has_tool_return:
        return ModelResponse(parts=[ToolCallPart("lookup_order", {"order_id": "A1001"})])
    return ModelResponse(
        parts=[TextPart('{"eligible": true, "reason": "未拆封且在十五天内", "days_left": 12}')]
    )


def build_agent() -> Agent:
    agent = Agent(
        FunctionModel(scripted),
        output_type=RefundDecision,
        deps_type=dict,
        instructions="你是售后审核助手，先查订单，再判断是否符合退货条件。",
    )
    agent.tool(lookup_order)
    return agent


def section_1_typed_run() -> None:
    print("=== 1. 一次带工具的类型化运行 ===")
    agent = build_agent()
    result = agent.run_sync("订单 A1001 能退吗？", deps=ORDERS)
    print(f"  输出类型：{type(result.output).__name__}")
    print(f"  输出：{result.output}")
    print(f"  用量：{result.usage}")
    print(f"  消息条数：{len(result.all_messages())}")
    for message in result.all_messages():
        parts = [getattr(part, "part_kind", "?") for part in getattr(message, "parts", [])]
        print(f"    {message.kind:<8} {parts}")


def section_2_schema() -> None:
    print("=== 2. 输出结构变成了模型看到的工具 ===")

    def peek(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for tool in info.output_tools:
            schema = tool.parameters_json_schema
            print(f"  输出工具名：{tool.name}")
            print(f"  必填字段：{schema.get('required')}")
            print(f"  字段名：{sorted(schema.get('properties', {}))}")
            desc = schema.get("properties", {}).get("reason", {}).get("description")
            print(f"  reason 的描述来自 Field：{desc}")
        return ModelResponse(parts=[TextPart('{"eligible": true, "reason": "未拆封", "days_left": 12}')])

    agent = Agent(FunctionModel(peek), output_type=RefundDecision)
    result = agent.run_sync("订单 A1001 能退吗？")
    print(f"  校验后输出：{result.output}")


def section_3_retry() -> None:
    print("=== 3. 校验失败：框架自己重试 ===")
    calls = {"n": 0}

    def bad_then_good(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        print(f"  第 {calls['n']} 次请求，消息数 {len(messages)}")
        if calls["n"] == 1:
            return ModelResponse(parts=[TextPart('{"eligible": "yes"}')])
        return ModelResponse(parts=[TextPart('{"eligible": true, "reason": "未拆封且在十五天内", "days_left": 12}')])

    agent = Agent(FunctionModel(bad_then_good), output_type=RefundDecision, retries=2)
    result = agent.run_sync("订单 A1001 能退吗？")
    print(f"  成功：{result.output}，总请求 {result.usage.requests} 次")
    last = result.all_messages()[-2]
    print(f"  重试时模型看到的最后一条请求片段：{[getattr(p, 'part_kind', '?') for p in last.parts]}")

    def always_bad(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("这不是 JSON")])

    agent2 = Agent(FunctionModel(always_bad), output_type=RefundDecision, retries=1)
    try:
        agent2.run_sync("订单 A1001 能退吗？")
    except UnexpectedModelBehavior as exc:
        print(f"  重试耗尽：{type(exc).__name__}: {exc}")


def main() -> None:
    section_1_typed_run()
    section_2_schema()
    section_3_retry()


if __name__ == "__main__":
    main()
