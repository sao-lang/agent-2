"""收窄：`LLMToolSelectorMiddleware`、`ToolCallLimitMiddleware`。

两件事不一样：前者减少**进请求的工具数**（省 token、提高选择准确率），
后者限制**工具被执行的次数**（挡住失控的执行侧）。

对照第 8 章的四种失控：工具选择器对应"工具太多选错"，调用上限对应"同一动作反复执行"。

不联网：模型侧走 `scripted_chat`，原理演示，不是模型实测。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain.agents.middleware import LLMToolSelectorMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.checkpoint.memory import InMemorySaver

from scripted_chat import chat_completion, scripted_chat, tool_call

TOOL_SPECS = [
    ("search_docs", "搜索产品文档与政策条文。"),
    ("search_code", "搜索源码文件与函数定义。"),
    ("get_order", "查询订单状态。"),
    ("send_sms", "给用户发短信。"),
    ("refund", "对订单发起退款。"),
]


def build_tools() -> list:
    """按上面的名字与说明批量造工具——这里用 11.1 的第三种写法，省掉五段装饰器。"""
    made = []
    for name, desc in TOOL_SPECS:
        def body(query: str = "", name: str = name) -> str:
            return json.dumps({"tool": name, "query": query}, ensure_ascii=False)

        made.append(StructuredTool.from_function(func=body, name=name, description=desc))
    return made


SELECTED: dict[str, list[str]] = {"tools": ["search_docs", "search_code", "get_order"]}


def selector_run() -> None:
    """一个模型同时扮演选择器和主模型：靠 `response_format` 区分两者。"""
    sent: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        sent.append(body)
        if "response_format" in body:
            return chat_completion(content=json.dumps(SELECTED, ensure_ascii=False))
        return chat_completion(content="我看一下文档。")

    tools = build_tools()

    def one(label: str, middleware: list) -> None:
        sent.clear()
        create_agent(scripted_chat(respond), tools=tools, middleware=middleware).invoke(
            {"messages": [HumanMessage("退款政策在哪份文档里？")]})
        main = sent[-1]
        print(f"  {label}")
        print(f"    请求总数 = {len(sent)}"
              f"（选择器 {len(sent) - 1} 次 + 主模型 1 次）")
        print(f"    主模型收到的工具 = {[t['function']['name'] for t in main['tools']]}")
        if len(sent) > 1:
            selector_body = sent[0]
            schema = selector_body["response_format"]["json_schema"]["schema"]
            keys = sorted(selector_body)
            candidates = [c["const"] for c in schema["properties"]["tools"]["items"]["anyOf"]]
            print(f"    选择器请求的键 = {keys}  tools 字段 = {selector_body.get('tools')}")
            print(f"    选择器给出的候选 = {candidates}")

    one("不装选择器", [])
    one("LLMToolSelectorMiddleware(max_tools=2)", [LLMToolSelectorMiddleware(max_tools=2)])
    one("max_tools=2 + always_include=['refund']",
        [LLMToolSelectorMiddleware(max_tools=2, always_include=["refund"])])


def limit_run(rounds: int) -> None:
    """一个反复要查同一个工具的主模型，看调用上限拦在哪一层。"""
    executed: dict[str, int] = {"n": 0}

    @tool("get_order")
    def get_order(order_id: str) -> str:
        """查询订单状态。"""
        executed["n"] += 1
        return json.dumps({"status": "已签收"}, ensure_ascii=False)

    def respond(index: int, body: dict) -> dict:
        if index < rounds:
            return chat_completion(
                tool_calls=[tool_call("get_order", {"order_id": f"A{1000 + index}"},
                                      f"call_{index}")],
                finish_reason="tool_calls")
        return chat_completion(content="结束。")

    def one(label: str, middleware: list) -> None:
        executed["n"] = 0
        out = create_agent(scripted_chat(respond), tools=[get_order],
                           middleware=middleware).invoke(
            {"messages": [HumanMessage("查订单")]},
            config={"configurable": {"thread_id": "t1"}})
        model_turns = sum(1 for m in out["messages"] if type(m).__name__ == "AIMessage")
        blocked = [m for m in out["messages"]
                   if type(m).__name__ == "ToolMessage" and m.status == "error"]
        print(f"  {label}")
        print(f"    模型轮数 = {model_turns}  工具执行 = {executed['n']}  "
              f"被拦回的 ToolMessage = {len(blocked)}")
        for m in blocked[:1]:
            print(f"    拦回内容 = {m.content}")
        tail = out["messages"][-1]
        print(f"    最后一条 = {type(tail).__name__} {tail.content!r}")

    one(f"{rounds} 轮工具调用，不装中间件", [])
    one(f"{rounds} 轮工具调用，run_limit=2", [ToolCallLimitMiddleware(run_limit=2)])


def main() -> None:
    print("=== 一、选择器：进请求的工具数 ===")
    selector_run()
    print()
    print("=== 二、调用上限：拦的是执行，不是轮数 ===")
    limit_run(rounds=5)
    print()
    print("=== 三、exit_behavior 与只限一个工具 ===")
    one_by_one()
    print()
    print("=== 四、thread_limit 跨运行累计 ===")
    thread_limit_run()


def thread_limit_run() -> None:
    """同一个 thread_id 上连着跑四次，每次只调一次工具，看累计在哪一次被拦住。"""
    executed: dict[str, int] = {"n": 0}

    @tool("get_order")
    def get_order(order_id: str) -> str:
        """查询订单状态。"""
        executed["n"] += 1
        return json.dumps({"status": "已签收"}, ensure_ascii=False)

    def respond(index: int, body: dict) -> dict:
        if index % 2 == 0:
            return chat_completion(
                tool_calls=[tool_call("get_order", {"order_id": "A1001"}, f"call_{index}")],
                finish_reason="tool_calls")
        return chat_completion(content="结束。")

    agent = create_agent(scripted_chat(respond), tools=[get_order],
                         middleware=[ToolCallLimitMiddleware(thread_limit=3)],
                         checkpointer=InMemorySaver())
    for run_index in range(4):
        executed["n"] = 0
        out = agent.invoke({"messages": [HumanMessage(f"第 {run_index} 次")]},
                           config={"configurable": {"thread_id": "t1"}})
        blocked = [m for m in out["messages"]
                   if type(m).__name__ == "ToolMessage" and m.status == "error"]
        print(f"  第 {run_index} 次运行：工具执行 = {executed['n']}  被拦回 = {len(blocked)}")


def one_by_one() -> None:
    """`exit_behavior` 两种取值、以及只限某一个工具。"""
    executed: dict[str, int] = {"n": 0}

    @tool("get_order")
    def get_order(order_id: str) -> str:
        """查询订单状态。"""
        executed["n"] += 1
        return json.dumps({"status": "已签收"}, ensure_ascii=False)

    def respond(index: int, body: dict) -> dict:
        if index < 3:
            return chat_completion(
                tool_calls=[tool_call("get_order", {"order_id": f"A{1000 + index}"},
                                      f"call_{index}")],
                finish_reason="tool_calls")
        return chat_completion(content="结束。")

    for label, mw in [
        ("exit_behavior='continue'（默认）", ToolCallLimitMiddleware(run_limit=2)),
        ("exit_behavior='end'", ToolCallLimitMiddleware(run_limit=2, exit_behavior="end")),
        ("只限 get_order，run_limit=1",
         ToolCallLimitMiddleware(tool_name="get_order", run_limit=1)),
    ]:
        executed["n"] = 0
        out = create_agent(scripted_chat(respond), tools=[get_order], middleware=[mw]).invoke(
            {"messages": [HumanMessage("查订单")]},
            config={"configurable": {"thread_id": "t1"}})
        tail = out["messages"][-1]
        print(f"  {label:34} 工具执行 = {executed['n']}  最后一条 = "
              f"{type(tail).__name__} {tail.content!r}")


if __name__ == "__main__":
    main()
