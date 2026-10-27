"""第 9 章 9.6：三种流式接口。

运行：python code/knowledge/ch09_lc_basic/streaming.py
脚本化后端：SSE 响应体由脚本给出，分块解析由 langchain-openai 真实完成。
原理演示，不是模型实测。
"""

import asyncio
import json

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from scripted_chat import scripted_chat, sse_content

PIECES = ("签收后", " 7 天内", "可退。", "条件：", "商品未拆封。")


def sse_response(index, body):
    """回放一份 SSE 响应体。"""
    return httpx.Response(200, content=sse_content(*PIECES),
                          headers={"content-type": "text/event-stream"})


def make_llm():
    """同步与异步两个传输层都由脚本化后端接管。"""
    return scripted_chat(sse_response)


def stream_chunks():
    """同步逐块。"""
    for chunk in make_llm().stream([HumanMessage("能退吗？")]):
        reason = chunk.response_metadata.get("finish_reason")
        print(f"{type(chunk).__name__:<16} content={chunk.content!r:<10} finish_reason={reason!r}")


async def astream_chunks():
    """异步逐块。"""
    async for chunk in make_llm().astream([HumanMessage("能退吗？")]):
        print(f"{type(chunk).__name__:<16} content={chunk.content!r}")


async def event_tree():
    """事件名与父子关系。"""
    llm = make_llm()
    wrap = RunnableLambda(lambda text: [HumanMessage(text)])
    pipeline = wrap | llm

    names = {}
    async for event in pipeline.astream_events("能退吗？", version="v2"):
        names.setdefault(event["run_id"], event.get("name"))
        parents = [names.get(pid, "?") for pid in event.get("parent_ids") or []]
        print(f"{event['event']:<22} {event.get('name'):<18} parent={parents or '(根)'}")


def aggregate():
    """把块拼成一条消息：正文、收尾原因、用量的位置各不相同。"""
    chunks = list(make_llm().stream([HumanMessage("能退吗？")]))
    total = chunks[0]
    for chunk in chunks[1:]:
        total = total + chunk
    print("块数:", len(chunks))
    print("拼出的文本:", total.content)
    print("finish_reason:", total.response_metadata.get("finish_reason"))
    print("usage_metadata:", total.usage_metadata)


if __name__ == "__main__":
    print("== stream() ==")
    stream_chunks()
    print()
    print("== astream() ==")
    asyncio.run(astream_chunks())
    print()
    print("== 块拼成整条 ==")
    aggregate()
    print()
    print("== astream_events(version='v2') ==")
    asyncio.run(event_tree())
