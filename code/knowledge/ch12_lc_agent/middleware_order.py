"""12.2 中间件钩子的执行顺序、短路与跳转。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/middleware_order.py
"""

from langchain.agents import create_agent
from langchain.agents.middleware import (AgentMiddleware, before_model, dynamic_prompt,
                                         hook_config)
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def echo(text: str) -> str:
    """把收到的文本原样返回。"""
    print(f"        [工具函数] echo({text})")
    return text


class Tracer(AgentMiddleware):
    """在每个钩子上打一行，用来看顺序。"""

    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag

    @property
    def name(self) -> str:
        return f"Tracer-{self.tag}"

    def before_agent(self, state, runtime):
        print(f"  {self.tag}.before_agent   msgs={len(state['messages'])}")
        return None

    def before_model(self, state, runtime):
        print(f"  {self.tag}.before_model   msgs={len(state['messages'])}")
        return None

    def wrap_model_call(self, request, handler):
        print(f"  {self.tag}.wrap_model_call 进入")
        response = handler(request)
        print(f"  {self.tag}.wrap_model_call 退出 {response.result[0].content!r}")
        return response

    def wrap_tool_call(self, request, handler):
        print(f"  {self.tag}.wrap_tool_call 进入 {request.tool_call['name']}")
        result = handler(request)
        print(f"  {self.tag}.wrap_tool_call 退出")
        return result

    def after_model(self, state, runtime):
        print(f"  {self.tag}.after_model")
        return None

    def after_agent(self, state, runtime):
        print(f"  {self.tag}.after_agent")
        return None


class Cutter(AgentMiddleware):
    """不调用 handler，直接给一条 AIMessage。"""

    def wrap_model_call(self, request, handler):
        print("  Cutter.wrap_model_call 短路")
        return AIMessage(content="被中间件拦下")


class JumpBare(AgentMiddleware):
    """跳到 end，但不补正文。"""

    def before_model(self, state, runtime):
        return {"jump_to": "end"}


class JumpWithMessage(AgentMiddleware):
    """跳到 end，并自己补一条正文。"""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        return {"jump_to": "end", "messages": [AIMessage(content="直接收尾")]}


class JumpToMissingNode(AgentMiddleware):
    """跳到图里不存在的节点。"""

    @hook_config(can_jump_to=["tools"])
    def before_model(self, state, runtime):
        return {"jump_to": "tools"}


def one_tool_then_answer(i, body):
    if i == 0:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("echo", {"text": "hi"}, "c1")])
    return chat_completion(content="好了")


def test_decorator_middleware() -> None:
    """函数式中间件：不用写类。"""
    print("\n=== 函数式中间件 + dynamic_prompt")
    seen = {}

    def capture(i, body):
        seen["first"] = (body["messages"][0]["role"], body["messages"][0]["content"])
        return chat_completion(content="ok")

    agent = create_agent(model=scripted_chat(capture),
                         middleware=[announce, rewrite_prompt])
    agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    print("  模型收到的第一条:", seen["first"])


@before_model
def announce(state, runtime):
    print("  [函数式 before_model] 最后一条是", type(state["messages"][-1]).__name__)
    return None


@dynamic_prompt
def rewrite_prompt(request):
    print("  [dynamic_prompt] 改写系统提示")
    return SystemMessage(content="你是退货客服，只回答退货问题。")


def main() -> None:
    print("=== 两个中间件的顺序 ===")
    agent = create_agent(model=scripted_chat(one_tool_then_answer), tools=[echo],
                         middleware=[Tracer("A"), Tracer("B")])
    agent.invoke({"messages": [{"role": "user", "content": "回声"}]})

    print("\n=== 短路时其余钩子 ===")
    agent = create_agent(model=scripted_chat(one_tool_then_answer),
                         middleware=[Tracer("A"), Cutter()])
    out = agent.invoke({"messages": [{"role": "user", "content": "回声"}]})
    print("  结果:", out["messages"][-1].content)

    print("\n=== 跳到 end 但不补正文 ===")
    agent = create_agent(model=scripted_chat(one_tool_then_answer),
                         middleware=[JumpBare()])
    out = agent.invoke({"messages": [{"role": "user", "content": "回声"}]})
    print("  消息:", [(type(m).__name__, m.content) for m in out["messages"]])

    print("\n=== 跳到 end 并补一条正文 ===")
    agent = create_agent(model=scripted_chat(one_tool_then_answer),
                         middleware=[JumpWithMessage()])
    out = agent.invoke({"messages": [{"role": "user", "content": "回声"}]})
    print("  消息:", [(type(m).__name__, m.content) for m in out["messages"]])

    print("\n=== 跳到图里没有的节点 ===")
    try:
        create_agent(model=scripted_chat(one_tool_then_answer),
                     middleware=[JumpToMissingNode()])
    except ValueError as exc:
        print("  ValueError:", str(exc)[:90])

    print("\n=== 同名中间件注册两次 ===")
    try:
        create_agent(model=scripted_chat(one_tool_then_answer), tools=[echo],
                     middleware=[Tracer("A"), Tracer("A")])
    except AssertionError as exc:
        print('  AssertionError:', exc)

    test_decorator_middleware()


if __name__ == "__main__":
    main()
