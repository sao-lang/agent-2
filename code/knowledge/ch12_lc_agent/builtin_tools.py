"""12.3 工具收窄与执行环境：选择器、模拟器、文件搜索、shell、provider 工具搜索。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/builtin_tools.py
"""

import os
import shutil
import tempfile

from langchain.agents import create_agent
from langchain.agents.middleware import (FilesystemFileSearchMiddleware,
                                         HostExecutionPolicy, LLMToolEmulator,
                                         LLMToolSelectorMiddleware,
                                         ProviderToolSearchMiddleware,
                                         ShellToolMiddleware)
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call


@tool
def refund(order_id: str) -> str:
    """发起退款。"""
    return "已受理"


@tool
def weather(city: str) -> str:
    """查天气。"""
    return "晴"


@tool
def calculator(expr: str) -> str:
    """算一个表达式。"""
    return "3"


def test_tool_selector() -> None:
    print("=== LLMToolSelectorMiddleware(max_tools=2, always_include=['refund'])")
    seen = {}

    def main_model(i, body):
        seen["tools"] = [t["function"]["name"] for t in body.get("tools", [])]
        return chat_completion(content="完成")

    def selector(i, body):
        print("    [选择器] 收到", len(body["messages"]), "条消息，从中挑工具")
        return chat_completion(content='{"tools": ["weather"]}')

    agent = create_agent(model=scripted_chat(main_model),
                         tools=[refund, weather, calculator],
                         middleware=[LLMToolSelectorMiddleware(
                             model=scripted_chat(selector),
                             max_tools=2, always_include=["refund"])])
    out = agent.invoke({"messages": [{"role": "user", "content": "退 A1001"}]})
    print("  主模型看到的工具:", seen.get("tools"))
    print("  最后:", out["messages"][-1].content)

    print("  --- 选了一个不在工具表里的名字：")
    try:
        create_agent(model=scripted_chat(main_model),
                     tools=[refund, weather, calculator],
                     middleware=[LLMToolSelectorMiddleware(
                         model=scripted_chat(lambda i, body: chat_completion(
                             content='{"tools": ["refund"]}')),
                         always_include=["refund"])]).invoke(
                             {"messages": [{"role": "user", "content": "退 A1001"}]})
    except ValueError as exc:
        print("  ValueError:", exc)


def test_tool_emulator() -> None:
    print("\n=== LLMToolEmulator")
    calls = {"n": 0}

    @tool
    def refund2(order_id: str) -> str:
        """发起退款。"""
        calls["n"] += 1
        return "真实退款执行了"

    def respond(i, body):
        if i == 0:
            return chat_completion(finish_reason="tool_calls",
                                   tool_calls=[tool_call("refund2", {"order_id": "A1001"}, "c1")])
        return chat_completion(content="完成")

    agent = create_agent(model=scripted_chat(respond), tools=[refund2],
                         middleware=[LLMToolEmulator(
                             model=scripted_chat(lambda i, body: chat_completion(
                                 content="[模拟] 退款已受理，未真实执行")))])
    out = agent.invoke({"messages": [{"role": "user", "content": "退款"}]})
    for message in out["messages"]:
        if type(message).__name__ == "ToolMessage":
            print("  ToolMessage:", repr(message.content[:70]))
    print("  真实工具函数被调用次数:", calls["n"])


def test_file_search() -> None:
    print("\n=== FilesystemFileSearchMiddleware")
    root = tempfile.mkdtemp(prefix="_fs_demo_")
    try:
        with open(os.path.join(root, "policy.md"), "w", encoding="utf-8") as handle:
            handle.write("# refund policy\nwindow: 7 days\n")
        with open(os.path.join(root, "price.md"), "w", encoding="utf-8") as handle:
            handle.write("# price\n99\n")
        with open(os.path.join(root, "cn.md"), "w", encoding="utf-8") as handle:
            handle.write("# 退货政策\n窗口 7 天\n")
        middleware = FilesystemFileSearchMiddleware(root_path=root, use_ripgrep=False)
        print("  注册的工具:", [t.name for t in middleware.tools])
        tools = {t.name: t for t in middleware.tools}

        def search(i, body):
            if i == 0:
                return chat_completion(finish_reason="tool_calls",
                                       tool_calls=[tool_call("glob_search",
                                                             {"pattern": "*.md"}, "c1")])
            if i == 1:
                return chat_completion(finish_reason="tool_calls",
                                       tool_calls=[tool_call("grep_search",
                                                             {"pattern": "window", "path": "/",
                                                              "output_mode": "content"}, "c2")])
            return chat_completion(content="窗口 7 天")

        agent = create_agent(model=scripted_chat(search), middleware=[middleware])
        out = agent.invoke({"messages": [{"role": "user", "content": "窗口几天"}]})
        for message in out["messages"]:
            if type(message).__name__ == "ToolMessage":
                print("  工具返回:", repr(message.content[:70]))
        print("  --- 同一个目录里搜中文：")
        print("  grep_search:", repr(tools["grep_search"].invoke(
            {"pattern": "窗口", "path": "/", "output_mode": "content"})))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_shell() -> None:
    print("\n=== ShellToolMiddleware（本机三次尝试）")
    import logging

    logging.disable(logging.CRITICAL)  # 让中间件的重试日志不刷屏
    cases = ((["powershell", "-NoLogo", "-NoProfile", "-Command", "-"], "powershell"),
             (["cmd.exe", "/Q"], "cmd.exe /Q"),
             (None, "默认（不传 shell_command）"))
    try:
        for command, label in cases:
            run_shell_case(command, label)
    finally:
        logging.disable(logging.NOTSET)


def run_shell_case(command, label) -> None:
    root = tempfile.mkdtemp(prefix="_sh_demo_")
    try:
        middleware = ShellToolMiddleware(
            workspace_root=root,
            execution_policy=HostExecutionPolicy(command_timeout=10),
            shell_command=command)
        agent = create_agent(
            model=scripted_chat(lambda i, body: chat_completion(
                finish_reason="tool_calls",
                tool_calls=[tool_call("shell", {"command": "echo hi"}, "c0")])
                if i == 0 else chat_completion(content="完成")),
            middleware=[middleware])
        out = agent.invoke({"messages": [{"role": "user", "content": "跑一条命令"}]})
        print(f"  [{label}]", repr(out["messages"][-2].content[:60]))
    except Exception as exc:  # noqa: BLE001 - 演示失败形态
        print(f"  [{label}] {type(exc).__name__}: {str(exc)[:60]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_provider_tool_search() -> None:
    print("\n=== ProviderToolSearchMiddleware")
    try:
        agent = create_agent(
            model=scripted_chat(lambda i, body: chat_completion(content="ok")),
            tools=[refund],
            middleware=[ProviderToolSearchMiddleware(searchable_tools=["refund"])])
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]})
    except Exception as exc:  # noqa: BLE001 - 演示失败形态
        print(f"  {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    test_tool_selector()
    test_tool_emulator()
    test_file_search()
    test_shell()
    test_provider_tool_search()
