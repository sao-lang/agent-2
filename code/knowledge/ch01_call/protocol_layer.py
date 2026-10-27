"""协议层对照：不用 SDK，用 http.client 手发一次请求。

`lifecycle.py` 里那一行 `client.chat.completions.create(...)` 展开成三步：
拼请求体、发 POST、把响应 JSON 解析出来。这一份就是这三步的手写版，
用来确认 SDK 没有做别的事——它发出去的是一条普通的 HTTP POST。

不联网。服务端是本机的一个 HTTP 服务，按请求里的 `metadata.case` 回放
手工构造的响应体；不是模型输出。
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

QUESTION = "能退吗？"


def body_of(case: str, content, finish_reason: str, usage: tuple[int, int]) -> dict:
    """按厂商接口的形状拼一份响应体。"""
    prompt, completion = usage
    return {
        "id": "chatcmpl-demo",
        "object": "chat.completion",
        "created": 1730000000,
        "model": "demo-model-2024",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content},
             "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                  "total_tokens": prompt + completion},
    }


RESPONSES = {
    "normal": body_of("normal", "签收后 7 天内可退。", "stop", (24, 9)),
    "truncated": body_of("truncated", "签收后 7 天内可退，条件是商品", "length", (24, 16)),
    "tool": body_of("tool", None, "tool_calls", (58, 19)),
    "filtered": body_of("filtered", "", "content_filter", (24, 0)),
}
RESPONSES["tool"]["choices"][0]["message"]["tool_calls"] = [
    {"id": "call_abc", "type": "function",
     "function": {"name": "get_order", "arguments": '{"order_id": "A1001"}'}}
]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        raw = json.dumps(RESPONSES[request["metadata"]["case"]], ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:
        pass


def build_request(case: str, max_tokens: int = 64) -> dict:
    """客户端发出的请求体。SDK 的每个参数都落在这里。"""
    return {
        "messages": [
            {"role": "system", "content": "你是退货政策助手，只回答与退货相关的政策。"},
            {"role": "user", "content": QUESTION},
        ],
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": max_tokens,
        "metadata": {"case": case},
    }


def call(port: int, request: dict) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(request, ensure_ascii=False).encode()
    conn.request("POST", "/v1/chat/completions", payload,
                 {"Content-Type": "application/json"})
    data = json.loads(conn.getresponse().read())
    conn.close()
    return data


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        print("请求体（http.client 手发，未经 SDK）")
        print(json.dumps(build_request("normal"), ensure_ascii=False, indent=2))
        print()
        print("响应体（HTTP 响应的原始字节）")
        print(json.dumps(call(port, build_request("normal")), ensure_ascii=False, indent=2))
        print()
        print("四个取值的原始 JSON 里各有什么：")
        for case in ("normal", "truncated", "tool", "filtered"):
            raw = call(port, build_request(case))
            choice = raw["choices"][0]
            usage = raw["usage"]
            print(f"  {case:<10}{choice['finish_reason']:<16}"
                  f"usage={usage['prompt_tokens']}+{usage['completion_tokens']:<4}"
                  f"content={choice['message']['content']!r}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
