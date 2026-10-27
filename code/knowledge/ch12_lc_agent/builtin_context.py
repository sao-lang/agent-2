"""12.3 上下文与安全：摘要、裁剪、待办、PII。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/builtin_context.py
"""

from langchain.agents import create_agent
from langchain.agents.middleware import (ClearToolUsesEdit,
                                         ContextEditingMiddleware,
                                         PIIDetectionError, PIIMiddleware,
                                         SummarizationMiddleware,
                                         TodoListMiddleware)
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def echo(text: str) -> str:
    """把收到的文本原样返回。"""
    return text


def three_tools_then_answer(i, body):
    if i < 3:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("echo", {"text": f"第{i}次"}, f"c{i}")])
    return chat_completion(content="回答")


def summarize(i, body):
    """摘要模型：只看到一条拼好的摘要请求。"""
    print(f"    [摘要模型被调用] 收到 {len(body['messages'])} 条消息")
    return chat_completion(content="<摘要>用户要求回声三次，已完成两次。</摘要>")


def test_summarization() -> None:
    print("=== SummarizationMiddleware(trigger=('messages', 4), keep=('messages', 1))")
    agent = create_agent(
        model=scripted_chat(three_tools_then_answer), tools=[echo],
        middleware=[SummarizationMiddleware(model=scripted_chat(summarize),
                                            trigger=("messages", 4),
                                            keep=("messages", 1))])
    out = agent.invoke({"messages": [{"role": "user", "content": "回声三次"}]})
    print("  最终消息数:", len(out["messages"]))
    for message in out["messages"]:
        print(f"    {type(message).__name__:<14}{str(message.content)[:60]!r}")


def test_context_editing() -> None:
    print("\n=== ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=60, keep=1)])")
    seen = {}

    def capture(i, body):
        seen[f"call{i}"] = [str(m.get("content"))[:24] for m in body["messages"]]
        if i < 3:
            return chat_completion(finish_reason="tool_calls",
                                   tool_calls=[tool_call("echo", {"text": f"第{i}次"}, f"c{i}")])
        return chat_completion(content="回答")

    agent = create_agent(model=scripted_chat(capture), tools=[echo],
                         middleware=[ContextEditingMiddleware(
                             edits=[ClearToolUsesEdit(trigger=60, keep=1)])])
    out = agent.invoke({"messages": [{"role": "user", "content": "回声三次"}]})
    for key, messages in seen.items():
        print(f"  {key}: {messages}")
    print("  state 里的工具消息:",
          [m.content for m in out["messages"] if type(m).__name__ == "ToolMessage"])


def test_todo() -> None:
    print("\n=== TodoListMiddleware")

    def plan(i, body):
        if i == 0:
            return chat_completion(finish_reason="tool_calls",
                                   tool_calls=[tool_call("write_todos", {"todos": [
                                       {"content": "查订单", "status": "in_progress"},
                                       {"content": "查政策", "status": "pending"}]}, "c1")])
        return chat_completion(content="好")

    agent = create_agent(model=scripted_chat(plan), middleware=[TodoListMiddleware()])
    out = agent.invoke({"messages": [{"role": "user", "content": "帮我退货"}]})
    print("  state 键:", list(out.keys()))
    print("  todos:", out["todos"])


def test_pii() -> None:
    print("\n=== PIIMiddleware('email', strategy='redact')")
    seen = {}

    def capture(i, body):
        seen["input"] = body["messages"][-1]["content"]
        return chat_completion(content="收到")

    agent = create_agent(model=scripted_chat(capture),
                         middleware=[PIIMiddleware("email", strategy="redact")])
    out = agent.invoke({"messages": [{"role": "user",
                                      "content": "我是 zhang@example.com，查 A1001"}]})
    print("  模型收到:", seen["input"])
    print("  state 里:", out["messages"][0].content)

    print("  --- strategy='block'：")
    agent = create_agent(model=scripted_chat(capture),
                         middleware=[PIIMiddleware("email", strategy="block")])
    try:
        agent.invoke({"messages": [{"role": "user", "content": "我是 zhang@example.com"}]})
    except PIIDetectionError as exc:
        print("  PIIDetectionError:", exc)


if __name__ == "__main__":
    test_summarization()
    test_context_editing()
    test_todo()
    test_pii()
