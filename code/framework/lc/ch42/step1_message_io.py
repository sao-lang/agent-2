"""第 42 章 step1：一次调用返回了什么——把 AIMessage 拆到底（离线）。

运行：
    python code/framework/lc/ch42/step1_message_io.py

上一级的痛点：
    "模型返回一个字符串" 是最大的误解。真实返回是一个对象，
    里面有 content / tool_calls / usage_metadata / response_metadata。

这一级做什么：
    不装任何"链"，只调一次模型接口，把返回对象的每个字段摊开看一遍。
    然后演示四种消息类型怎么组装成一段对话。

看完你要能回答：
    · 我该从哪个字段取文字？（content，不是 str(response)）
    · token 花在哪？（usage_metadata，不是自己数）
    · 怎么把多轮对话表示成"列表"？（各种 Message 类的列表）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import (  # noqa: E402
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from _fake import scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① 一次调用的返回，是个对象而不是字符串")
    llm = scripted(
        AIMessage(
            content="退款需要 7 个工作日到账。",
            usage_metadata={
                "input_tokens": 68,
                "output_tokens": 13,
                "total_tokens": 81,
            },
            response_metadata={"model_name": "gpt-4o-mini", "finish_reason": "stop"},
        )
    )
    msg = llm.invoke("退款多久到账？")

    print(f"  type(msg)                = {type(msg).__name__}")
    print(f"  msg.content              = {msg.content!r}")
    print(f"  msg.usage_metadata       = {msg.usage_metadata}")
    print(f"  msg.response_metadata    = {msg.response_metadata}")
    print(f"  msg.tool_calls           = {msg.tool_calls}")
    print(f"  bool(msg.id)             = {bool(msg.id)}")

    print("\n  → 取文字永远用 .content，不要 str(msg)（那是带元信息的调试表示）")

    line("② 四种消息：一段对话就是它们的列表")
    history = [
        SystemMessage("你是售后助手，不确定时不要承诺赔付金额。"),
        HumanMessage("我买的耳机坏了"),
        AIMessage("很抱歉。请问订单尾号是多少？"),
        HumanMessage("8848"),
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "query_order", "args": {"tail": "8848"}}],
        ),
        ToolMessage(content="订单 A1201，状态：已签收 12 天，在保修期内", tool_call_id="c1"),
    ]
    for i, m in enumerate(history, 1):
        role = type(m).__name__.replace("Message", "").lower()
        extra = ""
        if isinstance(m, AIMessage) and m.tool_calls:
            extra = f"  tool_calls={m.tool_calls}"
        if isinstance(m, ToolMessage):
            extra = f"  tool_call_id={m.tool_call_id}"
        print(f"  {i}. {role:<7} {m.content!r}{extra}")

    print("\n  → 模型没有记忆，它只是把这一整个列表重新读一遍")

    line("③ 一个必须知道的坑：content 不一定是纯文本")

    multimodal = AIMessage(
        content=[
            {"type": "text", "text": "图里是一张退货单。"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]
    )
    print(f"  type(content) = {type(multimodal.content).__name__}")
    print(f"  content       = {multimodal.content}")
    print(f"  str(content)  = {str(multimodal.content)[:60]}...")
    print("  → 直接 f-string 拼 content 会把整个 dict 拼进字符串，用户看到一堆大括号")

    line("④ 正确的取文本方式")

    def text_of(m: AIMessage) -> str:
        if isinstance(m.content, str):
            return m.content
        return "".join(p["text"] for p in m.content if isinstance(p, dict) and "text" in p)

    print(f"  抽出来的文本 = {text_of(multimodal)!r}")


if __name__ == "__main__":
    main()
