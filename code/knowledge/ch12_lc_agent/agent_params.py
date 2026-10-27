"""12.1 `create_agent` 的十五个参数：签名、注释版调用、一次真实运行。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/agent_params.py

模型是脚本化后端（原理演示，不是模型实测）。换成真实服务时只改
`scripted_chat(...)` 那一行：`ChatOpenAI(model="gpt-4.1", api_key=..., base_url=...)`。
"""

import inspect

import pydantic
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def get_order(order_id: str) -> str:
    """按订单号查签收天数和状态。"""
    return '{"order_id": "A1001", "days_since_delivery": 3, "status": "已签收"}'


class RefundAnswer(pydantic.BaseModel):
    """最终答复的结构。"""

    can_refund: bool
    days_left: int


def respond(i, body):
    """脚本：第 1 次要查订单，第 2 次给结构化答复。"""
    if i == 0:
        return chat_completion(finish_reason="tool_calls", usage=(104, 18),
                               tool_calls=[tool_call("get_order",
                                                     {"order_id": "A1001"}, "c1")])
    return chat_completion(finish_reason="tool_calls", usage=(180, 24),
                           tool_calls=[{"id": "c2", "type": "function",
                                        "function": {"name": "RefundAnswer",
                                                     "arguments": '{"can_refund": true,'
                                                                  ' "days_left": 4}'}}])


def show_signature() -> None:
    """把 15 个参数和默认值逐行打出来。"""
    sig = inspect.signature(create_agent)
    for name, param in sig.parameters.items():
        default = "" if param.default is inspect.Parameter.empty else f" = {param.default!r}"
        if default == " = ()":
            default = " = ()"
        print(f"{name}{default}")


def build_agent():
    """一份把全部参数都写出来的调用。"""
    return create_agent(
        model=scripted_chat(respond),           # 模型：字符串或 BaseChatModel 实例
        tools=[get_order],                      # 工具：callable / BaseTool / 内置工具 dict
        system_prompt="你是退货客服，只回答退货问题。",   # 系统消息，等价第 4 章的 system
        middleware=[ModelCallLimitMiddleware(run_limit=4)],  # 钩子列表，顺序即洋葱序
        response_format=RefundAnswer,           # 最终答复的结构，落到 structured_response
        state_schema=None,                      # 扩展 state 的字段；这里用默认 AgentState
        context_schema=None,                    # 每次调用传进来、不进 checkpoint 的只读上下文
        checkpointer=InMemorySaver(),           # 按 thread_id 存 state，多轮与中断都要它
        store=None,                             # 跨 thread 的长期存储
        interrupt_before=None,                  # 在某个节点前停下来（静态断点）
        interrupt_after=None,                   # 在某个节点后停下来（静态断点）
        debug=False,                            # 打印每个节点的输入与状态更新
        name="refund_agent",                    # 图的名字，挂成子图时用
        cache=None,                             # 图级缓存后端
        transformers=None,                      # 流式事件变换器
    )


def main() -> None:
    print("=== 签名 ===")
    show_signature()

    print("\n=== 运行 ===")
    agent = build_agent()
    print("图名字:", agent.name)
    out = agent.invoke({"messages": [{"role": "user", "content": "A1001 还能退吗"}]},
                       {"configurable": {"thread_id": "t-1"}})
    for message in out["messages"]:
        print(f"  {type(message).__name__:<14}{str(message.content)[:46]!r}")
    print("state 键:", list(out.keys()))
    print("structured_response:", out["structured_response"])


if __name__ == "__main__":
    main()
