"""事件树：一次 invoke 在 astream_events 里展开成什么。

没有 API key：模型换成本地脚本化后端，**原理演示，不是模型实测**。
从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/event_tree.py
"""

from __future__ import annotations

import asyncio

import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel

from scripted_chat import chat_completion, scripted_chat, sse_content

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只回答是否符合退货条件，一句话。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}


def respond(index: int, body: dict):
    if body.get("stream"):
        return httpx.Response(200, content=sse_content("符合", "退货", "条件。"),
                              headers={"content-type": "text/event-stream"})
    return chat_completion("符合退货条件。", usage=(42, 7))


def flat_chain():
    return PROMPT | scripted_chat(respond) | StrOutputParser()


def nested_chain():
    """并行里套两段链：深度会出现第二层。"""
    return RunnableParallel(
        verdict=PROMPT | scripted_chat(respond) | StrOutputParser(),
        chars=RunnableLambda(lambda x: len(x["state"])),
    )


async def collect(chain, inputs: dict) -> list[dict]:
    events = []
    async for ev in chain.astream_events(inputs, version="v2"):
        events.append(ev)
    return events


def pad(text: str, width: int) -> str:
    """按显示宽度补空格：一个中文字符占两列。"""
    used = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
    return text + " " * max(1, width - used)


def tree(events: list[dict]) -> None:
    """按 parent_ids 的层数缩进。流式事件只计数，不逐条打。"""
    print("  " + pad("事件名", 22) + pad("所在 Runnable", 34) + pad("run_id 尾 6 位", 16) + "层")
    print("  " + "-" * 68)
    stream_count: dict[str, int] = {}
    for ev in events:
        if ev["event"].endswith("_stream"):
            stream_count[ev["event"]] = stream_count.get(ev["event"], 0) + 1
            continue
        depth = len(ev["parent_ids"])
        indent = "  " * depth
        print("  " + pad(indent + ev["event"], 22 + 2 * depth)
              + pad(ev["name"], 34) + pad(ev["run_id"][-6:], 16) + str(depth))
    print()
    for event, n in stream_count.items():
        print(f"  （省略）{event} 共 {n} 条")
    print(f"  事件总数：{len(events)}")


def payload(events: list[dict]) -> None:
    """start 事件带输入，end 事件带输出：两头形状对上才能排查。"""
    for ev in events:
        if ev["event"] == "on_chat_model_start":
            msgs = ev["data"]["input"]["messages"][0]
            print(f"  on_chat_model_start：{len(msgs)} 条，类型 {[m.type for m in msgs]}")
        if ev["event"] == "on_chat_model_end":
            out = ev["data"]["output"]
            print(f"  on_chat_model_end：{type(out).__name__}，content={out.content!r}")
            print(f"                     usage_metadata={out.usage_metadata}")
        if ev["event"] == "on_chain_end" and not ev["parent_ids"]:
            print(f"  on_chain_end（根）：output={ev['data']['output']!r}")


async def main() -> None:
    flat = flat_chain()
    events = await collect(flat, CASE)
    print("== 一条平链的事件树 ==")
    tree(events)
    print()
    print("== start / end 两头各带什么 ==")
    payload(events)
    print()

    print("== 带并行的链：出现第二层 ==")
    events2 = await collect(nested_chain(), CASE)
    tree(events2)


if __name__ == "__main__":
    asyncio.run(main())
