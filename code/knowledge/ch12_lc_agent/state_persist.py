"""12.4 状态与持久化：state_schema、context_schema、checkpointer、store、cache。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/state_persist.py
"""

from dataclasses import dataclass

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import tool
from langgraph.cache.memory import InMemoryCache
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from typing_extensions import NotRequired

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def echo(text: str) -> str:
    """把收到的文本原样返回。"""
    return text


def one_tool_then_answer(i, body):
    if i == 0:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("echo", {"text": "hi"}, "c1")])
    return chat_completion(content="好了")


class MyState(AgentState):
    """在默认 AgentState 之外加两个字段。"""

    user_tier: NotRequired[str]
    tool_calls_made: NotRequired[int]


class CountCalls(AgentMiddleware):
    state_schema = MyState

    def after_model(self, state, runtime):
        calls = len(state["messages"][-1].tool_calls or [])
        return {"tool_calls_made": state.get("tool_calls_made", 0) + calls}


@dataclass
class Ctx:
    """一次调用的只读上下文，不进 checkpoint。"""

    tenant: str = "unknown"


class ReadCtx(AgentMiddleware):
    def before_model(self, state, runtime):
        print("    runtime.context.tenant =", runtime.context.tenant)
        return None


def test_checkpointer() -> None:
    print("=== checkpointer：同一个 thread_id 的两轮")
    agent = create_agent(
        model=scripted_chat(lambda i, body: chat_completion(content=f"第{i}次回答")),
        checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t-9"}}
    agent.invoke({"messages": [{"role": "user", "content": "第一轮"}]}, config)
    out = agent.invoke({"messages": [{"role": "user", "content": "第二轮"}]}, config)
    for message in out["messages"]:
        print(f"  {type(message).__name__:<14}{message.content!r}")
    state = agent.get_state(config)
    print("  checkpoint id 前缀:", state.config["configurable"]["checkpoint_id"][:8],
          "（每次运行不同）")
    print("  这条线程的历史 checkpoint 数:", len(list(agent.get_state_history(config))))
    other = agent.invoke({"messages": [{"role": "user", "content": "另一条线程"}]},
                         {"configurable": {"thread_id": "t-10"}})
    print("  新 thread_id 的消息数:", len(other["messages"]))


def test_state_schema() -> None:
    print("\n=== state_schema：自定义字段")
    agent = create_agent(model=scripted_chat(one_tool_then_answer), tools=[echo],
                         state_schema=MyState, middleware=[CountCalls()])
    out = agent.invoke({"messages": [{"role": "user", "content": "hi"}],
                        "user_tier": "gold"})
    print("  state 键:", list(out.keys()))
    print("  user_tier =", out.get("user_tier"), "| tool_calls_made =", out.get("tool_calls_made"))


def test_context_schema() -> None:
    print("\n=== context_schema：不进 checkpoint 的上下文")
    agent = create_agent(model=scripted_chat(one_tool_then_answer), tools=[echo],
                         context_schema=Ctx, middleware=[ReadCtx()])
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]},
                 context=Ctx(tenant="acme"))


def test_store() -> None:
    print("\n=== store：跨 thread 的长期存储")

    class ReadStore(AgentMiddleware):
        def before_model(self, state, runtime):
            item = runtime.store.get(("facts",), "policy")
            print("    runtime.store 读到:", item.value if item else None)
            return None

    store = InMemoryStore()
    store.put(("facts",), "policy", {"window_days": 7})
    agent = create_agent(model=scripted_chat(one_tool_then_answer), tools=[echo],
                         middleware=[ReadStore()], store=store)
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]})


def test_cache() -> None:
    print("\n=== cache：传了 cache 是否命中")
    calls = {"n": 0}

    def counting(i, body):
        calls["n"] += 1
        return chat_completion(content="回答")

    agent = create_agent(model=scripted_chat(counting), cache=InMemoryCache())
    message = {"messages": [{"role": "user", "content": "同一个问题"}]}
    agent.invoke(message)
    agent.invoke(message)
    print("  两次相同输入，模型被请求", calls["n"], "次")
    print("  model 节点的 cache_policy:", agent.nodes["model"].cache_policy)


if __name__ == "__main__":
    test_checkpointer()
    test_state_schema()
    test_context_schema()
    test_store()
    test_cache()
