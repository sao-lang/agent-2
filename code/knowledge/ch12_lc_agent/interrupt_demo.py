"""12.5 两种中断：HumanInTheLoopMiddleware 的动态中断与 interrupt_before/after 的静态断点。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/interrupt_demo.py
"""

import json

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def refund(order_id: str, amount: int) -> str:
    """按订单号发起退款。"""
    return f"已退款 {amount} 元，订单 {order_id}"


@tool
def echo(text: str) -> str:
    """把收到的文本原样返回。"""
    return text


def refund_then_answer(i, body):
    if i == 0:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("refund",
                                                     {"order_id": "A1001", "amount": 99}, "c1")])
    return chat_completion(content="退款已提交")


def test_human_in_the_loop() -> None:
    print("=== HumanInTheLoopMiddleware(interrupt_on={'refund': True})")
    agent = create_agent(model=scripted_chat(refund_then_answer), tools=[refund],
                         middleware=[HumanInTheLoopMiddleware(
                             interrupt_on={"refund": True})],
                         checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-1"}}

    first = agent.invoke({"messages": [{"role": "user", "content": "退 A1001 的 99 元"}]},
                         config)
    print("  返回键:", list(first.keys()))
    print("  消息:", [(type(m).__name__, m.content) for m in first["messages"]])
    payload = first["__interrupt__"][0].value
    print("  中断载荷:")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:520])
    print("  get_state().next:", agent.get_state(config).next)

    print("  --- 用 approve 恢复：")
    resumed = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
    for message in resumed["messages"]:
        print(f"    {type(message).__name__:<14}{str(message.content)[:40]!r}")
    print("  恢复后还有中断吗:", "__interrupt__" in resumed)


def test_reject() -> None:
    print("\n=== 用 reject 恢复")
    agent = create_agent(model=scripted_chat(refund_then_answer), tools=[refund],
                         middleware=[HumanInTheLoopMiddleware(
                             interrupt_on={"refund": True})],
                         checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-2"}}
    agent.invoke({"messages": [{"role": "user", "content": "退 A1001 的 99 元"}]}, config)
    resumed = agent.invoke(Command(resume={"decisions": [
        {"type": "reject", "message": "金额不对，先别退"}]}), config)
    for message in resumed["messages"]:
        print(f"  {type(message).__name__:<14}{str(message.content)[:50]!r}")


def test_edit_and_respond() -> None:
    print("\n=== 用 edit 恢复：审的人改参数")
    agent = create_agent(model=scripted_chat(refund_then_answer), tools=[refund],
                         middleware=[HumanInTheLoopMiddleware(
                             interrupt_on={"refund": True})],
                         checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-3"}}
    agent.invoke({"messages": [{"role": "user", "content": "退 A1001 的 99 元"}]}, config)
    resumed = agent.invoke(Command(resume={"decisions": [{
        "type": "edit",
        "edited_action": {"name": "refund",
                          "args": {"order_id": "A1001", "amount": 50}}}]}), config)
    for message in resumed["messages"]:
        print(f"  {type(message).__name__:<14}{message.content!r}")

    print("\n=== 用 respond 恢复：审的人代替工具回答")
    agent = create_agent(model=scripted_chat(refund_then_answer), tools=[refund],
                         middleware=[HumanInTheLoopMiddleware(
                             interrupt_on={"refund": True})],
                         checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-4"}}
    agent.invoke({"messages": [{"role": "user", "content": "退 A1001 的 99 元"}]}, config)
    resumed = agent.invoke(Command(resume={"decisions": [
        {"type": "respond", "message": "线下已退款，不要再发起线上退款"}]}), config)
    for message in resumed["messages"]:
        print(f"  {type(message).__name__:<14}{str(message.content)[:50]!r}")


def test_static_interrupts() -> None:
    print("\n=== interrupt_before=['tools']")
    agent = create_agent(model=scripted_chat(refund_then_answer), tools=[refund],
                         interrupt_before=["tools"], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "b-1"}}
    first = agent.invoke({"messages": [{"role": "user", "content": "退 A1001"}]}, config)
    print("  返回键:", list(first.keys()), "| 消息数:", len(first["messages"]))
    print("  next:", agent.get_state(config).next)
    out = agent.invoke(None, config)
    print("  继续后:", [type(m).__name__ for m in out["messages"]],
          "| 最后:", out["messages"][-1].content)

    print("\n=== interrupt_after=['tools']")
    agent = create_agent(model=scripted_chat(lambda i, body: chat_completion(
        finish_reason="tool_calls", tool_calls=[tool_call("echo", {"text": "hi"}, "c1")])
        if i == 0 else chat_completion(content="好了")),
        tools=[echo], interrupt_after=["tools"], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "a-1"}}
    first = agent.invoke({"messages": [{"role": "user", "content": "hi"}]}, config)
    print("  返回键:", list(first.keys()), "| 消息数:", len(first["messages"]))
    print("  next:", agent.get_state(config).next)
    out = agent.invoke(None, config)
    print("  继续后最后:", out["messages"][-1].content)

    print("\n=== interrupt_before 填不存在的节点")
    try:
        create_agent(model=scripted_chat(lambda i, body: chat_completion(content="ok")),
                     interrupt_before=["not_a_node"], checkpointer=InMemorySaver())
    except ValueError as exc:
        print("  ValueError:", exc)


if __name__ == "__main__":
    test_human_in_the_loop()
    test_reject()
    test_edit_and_respond()
    test_static_interrupts()
