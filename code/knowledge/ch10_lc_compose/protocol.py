"""Runnable 协议的四个入口：invoke / batch / stream / astream_events。

没有 API key：模型换成本地脚本化后端，请求照常编码、响应来自脚本里的字典。
**原理演示，不是模型实测。** 接真实服务时把 scripted_chat(respond) 换成
ChatOpenAI(model="gpt-4o-mini", api_key=..., base_url=...)，下面几段代码不用改。

从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/protocol.py
"""

from __future__ import annotations

import asyncio

import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from scripted_chat import chat_completion, scripted_chat, sse_content

TEMPLATE = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只回答是否符合退货条件，一句话。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])

CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}
CASES = [CASE,
         {"order_id": "A1002", "days": 8, "state": "已拆封"},
         {"order_id": "A1003", "days": 1, "state": "未拆封"}]

REQUESTS = {"n": 0}


def respond(index: int, body: dict):
    """脚本化后端：每次请求返回什么。流式请求返回 SSE 帧。"""
    REQUESTS["n"] += 1
    if body.get("stream"):
        return httpx.Response(200, content=sse_content("符合", "退货", "条件。"),
                              headers={"content-type": "text/event-stream"})
    return chat_completion("符合退货条件。", usage=(42, 7))


def build_chain():
    """模板 → 模型 → 解析器。三个 Runnable 用 | 连成一条 RunnableSequence。"""
    model = scripted_chat(respond)
    return TEMPLATE | model | StrOutputParser()


def show_shape(chain) -> None:
    """链自己声明了输入输出形状：输入是哪些键，输出是什么类型。"""
    inp = chain.get_input_schema().model_json_schema()
    out = chain.get_output_schema().model_json_schema()
    print("输入形状：")
    print(f"  required = {inp.get('required')}")
    print(f"  properties = {list(inp.get('properties', {}))}")
    print("输出形状：")
    print(f"  title = {out.get('title')}")
    print(f"  type = {out.get('type')}")
    print()


def invoke_part(chain) -> None:
    REQUESTS["n"] = 0
    print("== invoke：一次输入，一次输出 ==")
    out = chain.invoke(CASE)
    print(f"输入 {type(CASE).__name__} → 输出 {type(out).__name__}，是 str 的子类：{isinstance(out, str)}")
    print(f"值：{out!r}")
    print(f"HTTP 请求数：{REQUESTS['n']}")
    print()


def batch_part(chain) -> None:
    REQUESTS["n"] = 0
    print("== batch：多条输入 ==")
    outs = chain.batch(CASES, config={"max_concurrency": 1})
    print(f"输入 list[{len(CASES)}] → 输出 {type(outs).__name__}[{len(outs)}]")
    print(f"HTTP 请求数：{REQUESTS['n']}（不是 1：batch 是挨个发的）")
    print()


def batch_bad_input(chain) -> None:
    """输入少一个键：报错发生在装 messages 那一步，信息比调用栈有用。"""
    print("== batch：输入缺键 ==")
    try:
        chain.batch([{"order_id": "A1001"}], config={"max_concurrency": 1})
    except Exception as e:
        msg = str(e.args[0]) if e.args else str(e)
        lines = msg.splitlines()
        print(f"{type(e).__name__}: {lines[0]}")
        print(f"  {lines[1] if len(lines) > 1 else ''}")
    print()


def stream_part(chain) -> None:
    REQUESTS["n"] = 0
    print("== stream：一次输入，逐段输出 ==")
    pieces = list(chain.stream(CASE))
    print(f"收到 {len(pieces)} 段：{pieces}")
    print(f"拼起来：{''.join(pieces)!r}")
    print(f"其中空串 {sum(1 for p in pieces if p == '')} 段（收尾帧的 delta 是空的）")
    print(f"HTTP 请求数：{REQUESTS['n']}")
    print()


async def async_part(chain) -> None:
    print("== ainvoke ==")
    out = await chain.ainvoke(CASE)
    print(f"{type(out).__name__}：{out!r}")
    print()

    print("== abatch（max_concurrency=2）==")
    outs = await chain.abatch(CASES, config={"max_concurrency": 2})
    print(f"长度 {len(outs)}：{outs}")
    print()

    print("== astream ==")
    pieces = [piece async for piece in chain.astream(CASE)]
    print(f"{len(pieces)} 段：{pieces}")
    print()


def event_part() -> None:
    """事件流：同一条链跑一次，数出每一类事件的条数。"""
    chain = build_chain()

    async def collect() -> list[dict]:
        events = []
        async for ev in chain.astream_events(CASE, version="v2"):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    kinds: dict[str, int] = {}
    for ev in events:
        kinds[ev["event"]] = kinds.get(ev["event"], 0) + 1

    print("== astream_events：一次 invoke 对应的事件 ==")
    for event, n in kinds.items():
        print(f"  {event:<26}{n}")
    print(f"  {'合计':<24}{len(events)}")


def main() -> None:
    chain = build_chain()
    print("链的类型：", type(chain).__name__)
    print()
    show_shape(chain)
    invoke_part(chain)
    batch_part(chain)
    batch_bad_input(chain)
    stream_part(chain)
    asyncio.run(async_part(chain))
    event_part()


if __name__ == "__main__":
    main()
