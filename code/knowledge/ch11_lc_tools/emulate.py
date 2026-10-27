"""工具模拟：`LLMToolEmulator`。

它在工具调用的位置上再发一次模型请求，让模型"扮演"这个工具返回什么，
真实实现一次都不执行。用于**没有副作用地跑完整循环**，比如评测里反复跑同一个任务。

1.4.7 里这个中间件是有的，默认模型指向 anthropic，本机没装那个包，必须显式传 `model=`。

不联网：两个模型实例都走 `scripted_chat`，原理演示，不是模型实测。
换成真实服务时：`ChatOpenAI(model=..., api_key=..., base_url=...)`。
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain.agents.middleware import LLMToolEmulator
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call

REAL_CALLS: dict[str, int] = {"get_order": 0, "send_sms": 0}


@tool("get_order")
def get_order(order_id: str) -> str:
    """查询订单状态。返回 JSON：{"status": ..., "signed_days_ago": ...}。"""
    REAL_CALLS["get_order"] += 1
    return json.dumps({"status": "已签收", "signed_days_ago": 3}, ensure_ascii=False)


@tool("send_sms")
def send_sms(order_id: str) -> str:
    """给用户发一条短信。有副作用。"""
    REAL_CALLS["send_sms"] += 1
    return json.dumps({"sent": True, "order_id": order_id}, ensure_ascii=False)


def default_model_fails() -> None:
    """不传 `model=` 时会发生什么：贴的是真实的异常。"""
    try:
        LLMToolEmulator()
    except Exception as exc:
        print(f"  {type(exc).__name__}：{exc}")


def emulated_run() -> None:
    """主循环一个模型实例，模拟器另一个实例，两者靠脚本区分。"""
    main_sent: list[dict] = []
    emu_sent: list[dict] = []

    def main_respond(index: int, body: dict) -> dict:
        main_sent.append(body)
        if index == 0:
            return chat_completion(
                tool_calls=[tool_call("send_sms", {"order_id": "A1001"}, "call_sms")],
                finish_reason="tool_calls")
        return chat_completion(content="已通知用户。")

    def emu_respond(index: int, body: dict) -> dict:
        emu_sent.append(body)
        return chat_completion(content=json.dumps({"sent": True, "order_id": "A1001"},
                                                  ensure_ascii=False))

    emulator = scripted_chat(emu_respond)
    agent = create_agent(scripted_chat(main_respond), tools=[get_order, send_sms],
                         middleware=[LLMToolEmulator(model=emulator)])
    out = agent.invoke({"messages": [HumanMessage("通知一下用户")]})

    print(f"  模拟器收到的提示词：")
    print(f"    {emu_sent[0]['messages'][-1]['content']}")
    print(f"  模拟器没有带 tools 字段 = {'tools' not in emu_sent[0]}")
    for msg in out["messages"]:
        if type(msg).__name__ == "ToolMessage":
            print(f"  回灌 status={msg.status} content={msg.content}")
    print(f"  真实实现被调用次数 = {REAL_CALLS}")


def selective_run() -> None:
    """只模拟有副作用的那个，只读的照常真实执行。"""
    REAL_CALLS["get_order"] = 0
    REAL_CALLS["send_sms"] = 0

    def main_respond(index: int, body: dict) -> dict:
        if index == 0:
            return chat_completion(
                tool_calls=[tool_call("get_order", {"order_id": "A1001"}, "call_q"),
                            tool_call("send_sms", {"order_id": "A1001"}, "call_s")],
                finish_reason="tool_calls")
        return chat_completion(content="好。")

    def emu_respond(index: int, body: dict) -> dict:
        return chat_completion(content=json.dumps({"sent": True}, ensure_ascii=False))

    agent = create_agent(scripted_chat(main_respond), tools=[get_order, send_sms],
                         middleware=[LLMToolEmulator(tools=["send_sms"],
                                                     model=scripted_chat(emu_respond))])
    agent.invoke({"messages": [HumanMessage("查 A1001 并通知用户")]})
    print(f"  tools=['send_sms'] 时真实实现被调用次数 = {REAL_CALLS}")


def main() -> None:
    print("=== 一、不传 model 的失败 ===")
    default_model_fails()
    print()
    print("=== 二、模拟器替掉工具执行 ===")
    emulated_run()
    print()
    print("=== 三、只模拟有副作用的工具 ===")
    selective_run()


if __name__ == "__main__":
    main()
