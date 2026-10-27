"""12.3 预算与重试：六个内置中间件各跑一遍。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/builtin_budget.py
"""

from langchain.agents import create_agent
from langchain.agents.middleware import (ModelCallLimitMiddleware,
                                         ModelFallbackMiddleware,
                                         ModelRetryMiddleware,
                                         ToolCallLimitMiddleware,
                                         ToolErrorMiddleware, ToolRetryMiddleware)
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def echo(text: str) -> str:
    """把收到的文本原样返回。"""
    return text


@tool
def boom(reason: str) -> str:
    """总是抛错，用来看错误怎么回到模型。"""
    raise RuntimeError(f"下游超时：{reason}")


def always_tool(i, body):
    """永不收尾：每次都要调工具。"""
    return chat_completion(finish_reason="tool_calls",
                           tool_calls=[tool_call("echo", {"text": f"第{i}次"}, f"c{i}")])


def two_then_answer(i, body):
    if i < 2:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("echo", {"text": f"第{i}次"}, f"c{i}")])
    return chat_completion(content="完成")


def test_model_call_limit() -> None:
    print("=== ModelCallLimitMiddleware(run_limit=2)")
    agent = create_agent(model=scripted_chat(always_tool), tools=[echo],
                         middleware=[ModelCallLimitMiddleware(run_limit=2)])
    out = agent.invoke({"messages": [{"role": "user", "content": "开始"}]})
    for message in out["messages"]:
        print(f"  {type(message).__name__:<14}{str(message.content)[:52]!r}")


def test_model_retry() -> None:
    print("\n=== ModelRetryMiddleware(max_retries=2)")
    calls = {"n": 0}

    def flaky(i, body):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(f"上游 503（第{calls['n']}次）")
        return chat_completion(content="第三次成功")

    agent = create_agent(model=scripted_chat(flaky),
                         middleware=[ModelRetryMiddleware(max_retries=2,
                                                          initial_delay=0, jitter=False)])
    out = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    print("  结果:", out["messages"][-1].content, "| 模型被请求", calls["n"], "次")


def test_model_fallback() -> None:
    print("\n=== ModelFallbackMiddleware")

    def broken(i, body):
        raise RuntimeError("主模型 503")

    backup = scripted_chat(lambda i, body: chat_completion(content="备用模型回答"))
    agent = create_agent(model=scripted_chat(broken),
                         middleware=[ModelFallbackMiddleware(backup)])
    out = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    print("  结果:", out["messages"][-1].content)


def test_tool_call_limit() -> None:
    print("\n=== ToolCallLimitMiddleware(tool_name='echo', run_limit=1)")
    agent = create_agent(model=scripted_chat(two_then_answer), tools=[echo],
                         middleware=[ToolCallLimitMiddleware(tool_name="echo", run_limit=1)])
    out = agent.invoke({"messages": [{"role": "user", "content": "开始"}]})
    for message in out["messages"]:
        if type(message).__name__ == "ToolMessage":
            print("  ToolMessage:", repr(message.content[:60]))


def test_tool_retry() -> None:
    print("\n=== ToolRetryMiddleware(max_retries=2)")
    calls = {"n": 0}

    @tool
    def flaky_tool(x: str) -> str:
        """前两次失败，第三次成功。"""
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(f"工具第{calls['n']}次失败")
        return f"成功:{x}"

    def one_call(i, body):
        if i == 0:
            return chat_completion(finish_reason="tool_calls",
                                   tool_calls=[tool_call("flaky_tool", {"x": "a"}, "c1")])
        return chat_completion(content="完成")

    agent = create_agent(model=scripted_chat(one_call), tools=[flaky_tool],
                         middleware=[ToolRetryMiddleware(max_retries=2,
                                                         initial_delay=0, jitter=False)])
    out = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    for message in out["messages"]:
        if type(message).__name__ == "ToolMessage":
            print("  ToolMessage:", repr(message.content), "| status =", message.status)
    print("  工具函数被调用", calls["n"], "次")


def test_tool_error() -> None:
    print("\n=== ToolErrorMiddleware(on_error=...)")

    def one_boom(i, body):
        if i == 0:
            return chat_completion(finish_reason="tool_calls",
                                   tool_calls=[tool_call("boom", {"reason": "slow"}, "c1")])
        return chat_completion(content="收到错误")

    agent = create_agent(
        model=scripted_chat(one_boom), tools=[boom],
        middleware=[ToolErrorMiddleware(
            on_error=lambda exc, req: f"工具 {req.tool_call['name']} 失败：{exc}")])
    out = agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    for message in out["messages"]:
        if type(message).__name__ == "ToolMessage":
            print("  ToolMessage:", repr(message.content), "| status =", message.status)

    print("  --- 不传 on_error 时：")
    try:
        ToolErrorMiddleware()
    except ValueError as exc:
        print("  ValueError:", exc)


def test_thread_limit() -> None:
    print("\n=== ModelCallLimitMiddleware(thread_limit=3) + checkpointer")
    from langgraph.checkpoint.memory import InMemorySaver

    agent = create_agent(model=scripted_chat(always_tool), tools=[echo],
                         checkpointer=InMemorySaver(),
                         middleware=[ModelCallLimitMiddleware(thread_limit=3)])
    config = {"configurable": {"thread_id": "tt"}}
    for round_no in range(2):
        out = agent.invoke({"messages": [{"role": "user", "content": f"第{round_no}轮"}]},
                           config)
        print(f"  第{round_no}轮 消息数={len(out['messages'])} 最后={out['messages'][-1].content!r}")


if __name__ == "__main__":
    test_model_call_limit()
    test_model_retry()
    test_model_fallback()
    test_tool_call_limit()
    test_tool_retry()
    test_tool_error()
    test_thread_limit()
