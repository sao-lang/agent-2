"""脚本化后端：一个本地 HTTP 服务，按脚本回放 OpenAI 兼容的响应。

用途：在没有 API key、没有外网的环境里，让 `openai` 客户端走一遍真实的
HTTP 请求与响应解析。**它不产生模型输出**，正文引用它的输出时必须标注
"原理演示，不是实测"。

每个示例目录放一份本文件的副本，脚本直接 `from fake_server import ...`，
不跨章 import，保证每个目录都能单独运行。
"""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def chat_completion(content="", tool_calls=None, finish_reason="stop",
                    usage=(0, 0), model="demo-model"):
    """构造一份与厂商响应同构的字典。"""
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
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call(name, arguments, call_id="call_demo"):
    """构造响应里的一个 `tool_calls` 元素。`arguments` 是 JSON 字符串。"""
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


def stream_pieces(pieces):
    """把若干文本增量拼成一份 SSE 响应体（dict 形式返回给 `scripted_server`）。"""
    return {"_sse": [
        {"id": "chatcmpl-demo", "object": "chat.completion.chunk", "created": 0,
         "model": "demo-model",
         "choices": [{"index": 0, "delta": piece, "finish_reason": None}]}
        for piece in pieces
    ] + [{"id": "chatcmpl-demo", "object": "chat.completion.chunk", "created": 0,
          "model": "demo-model",
          "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]}


@contextmanager
def scripted_server(respond):
    """起一个本机服务，`respond(index, body)` 返回要回放的响应字典。

    `index` 是从 0 开始的请求序号，`body` 是解析后的请求体。
    返回字典里带 `_sse` 时，按 SSE 分块返回。
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers["content-length"])
            body = json.loads(self.rfile.read(length))
            reply = respond(self.server.request_count, body)
            self.server.request_count += 1
            if "_sse" in reply:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                for piece in reply["_sse"]:
                    self.wfile.write(b"data: " + json.dumps(piece).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
                return
            raw = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.request_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()


def client_for(base_url):
    """拿到一个指向脚本化后端的 openai 客户端（本机回环，不走系统代理）。"""
    import httpx
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key="sk-test",
                  http_client=httpx.Client(trust_env=False))
