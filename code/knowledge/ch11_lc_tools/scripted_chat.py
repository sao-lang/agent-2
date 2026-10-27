"""脚本化聊天模型：把 `ChatOpenAI` 接到一份写死的脚本上。

用途：没有 API key、没有外网时，仍然让真实的 LangChain 代码走完
序列化 → 请求 → 解析 → 消息对象这一整条路。**它不产生模型输出**，
正文引用输出时必须标注"原理演示，不是实测"。

做法是给 `ChatOpenAI` 换一个 httpx 传输层：请求照常编码，响应来自
下面这份脚本。每个示例目录放一份副本，保证目录能单独运行。

接入真实服务时，把 `scripted_chat(...)` 换成
`ChatOpenAI(model=..., api_key=..., base_url=...)` 即可，其余代码不动。
"""

import json

import httpx
from langchain_openai import ChatOpenAI


def chat_completion(content="", tool_calls=None, finish_reason="stop",
                    usage=(0, 0), model="demo-model"):
    """一份与厂商响应同构的字典。"""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    prompt_tokens, completion_tokens = usage
    return {
        "id": "chatcmpl-demo",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": prompt_tokens,
                  "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


def tool_call(name, arguments, call_id="call_demo"):
    """构造响应里的一个 `tool_calls` 元素。`arguments` 是 JSON 字符串。"""
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def sse_content(*pieces):
    """把若干文本增量拼成 SSE 响应体。"""
    chunks = [{"id": "c", "object": "chat.completion.chunk", "created": 0,
               "model": "demo-model",
               "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
              for piece in pieces]
    chunks.append({"id": "c", "object": "chat.completion.chunk", "created": 0,
                   "model": "demo-model",
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"


def scripted_chat(respond, **kwargs):
    """返回一个把请求交给 `respond(index, body)` 的 `ChatOpenAI`。

    `respond` 返回响应字典；返回 `httpx.Response` 时原样使用（流式用）。
    """

    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        reply = respond(counter["n"], body)
        counter["n"] += 1
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)

    return ChatOpenAI(
        model="demo-model",
        api_key="sk-test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ),
        **kwargs,
    )
