"""12.6 同一份剧本：手写循环 vs create_agent。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/handwritten_vs_framework.py
"""

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call

MAX_STEPS = 8


@tool
def get_order(order_id: str) -> str:
    """按订单号查签收天数。"""
    return '{"order_id": "A1001", "days_since_delivery": 3}'


@tool
def get_policy() -> str:
    """查退货政策窗口。"""
    return '{"window_days": 7}'


def script(i, body):
    """三步剧本：查订单 → 查政策 → 作答。"""
    if i == 0:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("get_order", {"order_id": "A1001"}, "c1")])
    if i == 1:
        return chat_completion(finish_reason="tool_calls",
                               tool_calls=[tool_call("get_policy", {}, "c2")])
    return chat_completion(content="可以退：签收 3 天，窗口 7 天。")


def handwritten() -> dict:
    """第 7 章那个循环的最小版：自己请求、自己执行、自己判终止。"""
    tools = {"get_order": get_order, "get_policy": get_policy}
    messages = [{"role": "user", "content": "A1001 还能退吗"}]
    calls = 0
    trace = []
    status = "max_steps"
    for step in range(1, MAX_STEPS + 1):
        reply = script(calls, {"messages": messages})
        calls += 1
        message = reply["choices"][0]["message"]
        if not message.get("tool_calls"):
            messages.append({"role": "assistant", "content": message["content"]})
            status = "done"
            break
        for call in message["tool_calls"]:
            name = call["function"]["name"]
            trace.append(f"{step}: {name}")
            messages.append({"role": "assistant", "content": "",
                             "tool_calls": [call]})
            messages.append({"role": "tool", "content": tools[name].invoke(
                call["function"]["arguments"])})
    return {"status": status, "steps": calls, "trace": trace, "messages": len(messages)}


def framework() -> dict:
    counter = {"n": 0}

    def counting(i, body):
        counter["n"] += 1
        return script(i, body)

    agent = create_agent(model=scripted_chat(counting), tools=[get_order, get_policy],
                         system_prompt="你是退货客服。")
    out = agent.invoke({"messages": [{"role": "user", "content": "A1001 还能退吗"}]})
    return {"messages": [type(m).__name__ for m in out["messages"]],
            "model_calls": counter["n"],
            "state_keys": list(out.keys())}


def framework_with_limit() -> dict:
    counter = {"n": 0}

    def counting(i, body):
        counter["n"] += 1
        return script(i, body)

    agent = create_agent(model=scripted_chat(counting), tools=[get_order, get_policy],
                         middleware=[ModelCallLimitMiddleware(run_limit=1)])
    out = agent.invoke({"messages": [{"role": "user", "content": "A1001 还能退吗"}]})
    return {"model_calls": counter["n"], "last": out["messages"][-1].content}


if __name__ == "__main__":
    print("=== 手写循环 ===")
    run = handwritten()
    print("  status =", run["status"], "| steps =", run["steps"],
          "| messages =", run["messages"])
    print("  trace  =", run["trace"])

    print("\n=== create_agent ===")
    result = framework()
    print("  消息:", result["messages"])
    print("  模型调用次数:", result["model_calls"])
    print("  state 键:", result["state_keys"], "（没有 status / steps）")

    print("\n=== create_agent + ModelCallLimitMiddleware(run_limit=1) ===")
    limited = framework_with_limit()
    print("  模型调用次数:", limited["model_calls"])
    print("  最后一条:", limited["last"])
