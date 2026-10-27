"""错误与重试：`ToolRetryMiddleware`、`ToolErrorMiddleware`。

对照第 6 章手写的三个 `except`：那一版把所有异常都编成一条 `tool` 消息回灌。
框架版分成两件事——重试几个回合、失败之后这一次怎么交代——各由一个中间件管。

不联网：模型侧走 `scripted_chat`，原理演示，不是模型实测。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json
from typing import Type

from langchain.agents import create_agent
from langchain.agents.middleware import ToolErrorMiddleware, ToolRetryMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import BaseModel, Field

from scripted_chat import chat_completion, scripted_chat, tool_call

TRIES: dict[str, int] = {"n": 0}


class FragileArgs(BaseModel):
    sku: str = Field(description="商品编号")


def make_tool(fail_until: int) -> object:
    """造一个前 `fail_until` 次抛 TimeoutError 的工具。"""

    @tool("charge_card")
    def charge_card(order_id: str) -> str:
        """对订单发起扣款。下游偶尔超时。"""
        TRIES["n"] += 1
        if TRIES["n"] <= fail_until:
            raise TimeoutError(f"上游网关超时（第 {TRIES['n']} 次）")
        return json.dumps({"ok": True, "order_id": order_id, "attempt": TRIES["n"]},
                          ensure_ascii=False)

    return charge_card


def respond(index: int, body: dict) -> dict:
    if index == 0:
        return chat_completion(tool_calls=[tool_call("charge_card", {"order_id": "A1001"},
                                                     "call_pay")],
                               finish_reason="tool_calls")
    return chat_completion(content="收到结果。")


def run(label: str, fail_until: int, middleware: list) -> None:
    """跑一次扣款，打印工具被调了几次、回灌给模型的是什么。"""
    TRIES["n"] = 0
    agent = create_agent(scripted_chat(respond), tools=[make_tool(fail_until)],
                         middleware=middleware)
    print(f"  {label}")
    try:
        out = agent.invoke({"messages": [HumanMessage("给 A1001 扣款")]})
        for msg in out["messages"]:
            if type(msg).__name__ == "ToolMessage":
                print(f"    回灌 status={msg.status} content={msg.content}")
    except Exception as exc:
        print(f"    抛出 {type(exc).__name__}：{exc}")
    print(f"    工具执行次数 = {TRIES['n']}")


def on_error(exc: Exception, request: ToolCallRequest) -> str:
    """把异常转成给模型看的内容。返回 None 表示交给上层抛。"""
    return f"{type(exc).__name__}：{exc}（工具 {request.tool_call['name']}）"


def main() -> None:
    print("=== 一、不加中间件 ===")
    run("没有中间件，工具抛 TimeoutError", 99, [])

    print()
    print("=== 二、只加重试 ===")
    run("max_retries=2，前两次失败第三次成功", 2,
        [ToolRetryMiddleware(max_retries=2, initial_delay=0.01, jitter=False)])
    run("max_retries=2，一直失败（默认 on_failure='continue'）", 99,
        [ToolRetryMiddleware(max_retries=2, initial_delay=0.01, jitter=False)])
    run("max_retries=2，一直失败，on_failure 传函数", 99,
        [ToolRetryMiddleware(max_retries=2, initial_delay=0.01, jitter=False,
                             on_failure=lambda exc: f"扣款失败：{exc}；请不要重试同一订单。")])

    print()
    print("=== 三、只加错误回灌 ===")
    run("ToolErrorMiddleware(on_error=...)", 99,
        [ToolErrorMiddleware(on_error=on_error)])
    run("on_error 返回 None，异常照样抛出去", 99,
        [ToolErrorMiddleware(on_error=lambda exc, req: None)])

    print()
    print("=== 四、两个一起用：重试在内，回灌在外 ===")
    run("retry(on_failure='error') + ToolErrorMiddleware", 99,
        [ToolErrorMiddleware(on_error=on_error),
         ToolRetryMiddleware(max_retries=1, initial_delay=0.01, jitter=False,
                             on_failure="error")])

    print()
    print("=== 五、参数绑定错误不需要中间件 ===")
    bad_args()

    print()
    print("=== 六、工具自己声明怎么处理 ToolException ===")
    handle_inside_tool()

    print()
    print("=== 七、retry_on 只重试值得重试的异常 ===")
    retry_on_filter()


def retry_on_filter() -> None:
    """同一个工具抛两种异常：超时该重试，参数类错误不该。"""

    tried = {"n": 0}

    @tool("charge_card")
    def charge_card(order_id: str) -> str:
        """对订单发起扣款。"""
        tried["n"] += 1
        raise ValueError(f"业务参数不合法（第 {tried['n']} 次）")

    def respond(index: int, body: dict) -> dict:
        if index == 0:
            return chat_completion(tool_calls=[tool_call("charge_card", {"order_id": "A1001"},
                                                         "call_pay")],
                                   finish_reason="tool_calls")
        return chat_completion(content="结束。")

    for label, retry_on in [("默认 retry_on（所有 Exception）", None),
                            ("retry_on=(TimeoutError,)", (TimeoutError,))]:
        tried["n"] = 0
        kwargs = {} if retry_on is None else {"retry_on": retry_on}
        agent = create_agent(scripted_chat(respond), tools=[charge_card],
                             middleware=[ToolRetryMiddleware(max_retries=2,
                                                             initial_delay=0.01,
                                                             jitter=False, **kwargs)])
        try:
            agent.invoke({"messages": [HumanMessage("给 A1001 扣款")]})
            print(f"  {label:32} 工具执行 = {tried['n']}")
        except Exception as exc:
            print(f"  {label:32} 工具执行 = {tried['n']}  抛出 {type(exc).__name__}")


def bad_args() -> None:
    """模型把参数名写错：这一层在工具执行之前就被拦下，编成 error ToolMessage。"""

    @tool("get_order")
    def get_order(order_id: str) -> str:
        """查询订单状态。"""
        return json.dumps({"status": "已签收"}, ensure_ascii=False)

    def respond_wrong(index: int, body: dict) -> dict:
        if index == 0:
            return chat_completion(tool_calls=[tool_call("get_order", {"city": "杭州"},
                                                         "call_bad")],
                                   finish_reason="tool_calls")
        return chat_completion(content="收到错误。")

    out = create_agent(scripted_chat(respond_wrong), tools=[get_order]).invoke(
        {"messages": [HumanMessage("查订单")]})
    for msg in out["messages"]:
        if type(msg).__name__ == "ToolMessage":
            print(f"    回灌 status={msg.status} content={msg.content}")


def handle_inside_tool() -> None:
    """`ToolException` 加 `handle_tool_error`：不用中间件，异常在工具边界就转成消息。"""

    class FragileTool(BaseTool):
        name: str = "fragile"
        description: str = "查询库存。上游偶尔返回 409。"
        args_schema: Type[BaseModel] = FragileArgs
        handle_tool_error: bool | str = "库存不足，请换一个商品。"

        def _run(self, sku: str) -> str:
            raise ToolException(f"上游返回 409：{sku}")

    tool_obj = FragileTool()
    call = {"name": "fragile", "args": {"sku": "X1"}, "id": "call_f", "type": "tool_call"}
    direct = tool_obj.invoke(call)
    print(f"    直接 invoke 拿到 {type(direct).__name__} status={direct.status}")
    print(f"    内容 = {direct.content}")

    def respond(index: int, body: dict) -> dict:
        if index == 0:
            return chat_completion(tool_calls=[tool_call("fragile", {"sku": "X1"}, "call_f")],
                                   finish_reason="tool_calls")
        return chat_completion(content="收到。")

    out = create_agent(scripted_chat(respond), tools=[tool_obj]).invoke(
        {"messages": [HumanMessage("X1 有货吗")]})
    for msg in out["messages"]:
        if type(msg).__name__ == "ToolMessage":
            print(f"    回灌 status={msg.status} content={msg.content}")


if __name__ == "__main__":
    main()
