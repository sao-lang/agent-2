"""流式下的 JsonOutputParser：给的是累积后的对象，不是增量补丁。

没有 API key：模型换成本地脚本化后端，**原理演示，不是模型实测**。
从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/stream_json.py
"""

from __future__ import annotations

import asyncio
import json

import httpx
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from scripted_chat import chat_completion, scripted_chat, sse_content

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只输出 JSON，不要 markdown 包裹。"),
    ("human", "订单 {order_id}，签收 {days} 天。判定是否符合退货条件。"),
])
CASE = {"order_id": "A1001", "days": 3}
# 三段增量：第一段单独看不是合法 JSON
PIECES = ('{"order_id": "A1001", ', '"eligible": true, ', '"days": 3}')


def respond(index: int, body: dict):
    if body.get("stream"):
        return httpx.Response(200, content=sse_content(*PIECES),
                              headers={"content-type": "text/event-stream"})
    return chat_completion("".join(PIECES), usage=(42, 7))


async def main() -> None:
    chain = PROMPT | scripted_chat(respond) | JsonOutputParser()

    print("== astream：每段是一份累积结果 ==")
    async for piece in chain.astream(CASE):
        print(f"  {json.dumps(piece, ensure_ascii=False)}")

    print()
    print("== ainvoke：同一份输入，一次给完整对象 ==")
    print(f"  {await chain.ainvoke(CASE)}")


if __name__ == "__main__":
    asyncio.run(main())
