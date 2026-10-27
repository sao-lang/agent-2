"""一次调用里，每个字段由谁产生。

不联网。这里用一个本地 HTTP 服务器扮演"模型服务端"，用 http.client 发真实请求，
所以 requests 和 responses 都是真实在网络上传的 JSON，不是本地函数调用。

服务端的行为脚本化：请求里带什么标记，就返回哪种响应。它返回的是按厂商接口
（OpenAI 兼容格式）手工构造的响应体，用来演示字段结构；不是真实模型的输出。
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------- 假服务端

RESPONSES = {
    # 正常结束
    "normal": {
        "id": "chatcmpl-01",
        "object": "chat.completion",
        "created": 1730000000,
        "model": "demo-model-2024",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "签收后 7 天内可退。"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 24,
            "completion_tokens": 9,
            "total_tokens": 33,
        },
    },
    # 输出被截断
    "truncated": {
        "id": "chatcmpl-02",
        "object": "chat.completion",
        "created": 1730000000,
        "model": "demo-model-2024",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "签收后 7 天内可退，条件是商品"},
                "finish_reason": "length",
            }
        ],
        "usage": {"prompt_tokens": 24, "completion_tokens": 16, "total_tokens": 40},
    },
    # 模型要求调用工具
    "tool": {
        "id": "chatcmpl-03",
        "object": "chat.completion",
        "created": 1730000000,
        "model": "demo-model-2024",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {
                                "name": "get_order",
                                "arguments": '{"order_id": "A1001"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 58, "completion_tokens": 19, "total_tokens": 77},
    },
    # 被内容过滤
    "filtered": {
        "id": "chatcmpl-04",
        "object": "chat.completion",
        "created": 1730000000,
        "model": "demo-model-2024",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "content_filter",
            }
        ],
        "usage": {"prompt_tokens": 24, "completion_tokens": 0, "total_tokens": 24},
    },
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        raw = self.rfile.read(length)
        request = json.loads(raw)

        # 服务端按请求里的标记决定返回哪种响应
        marker = request.get("metadata", {}).get("case", "normal")
        body = json.dumps(RESPONSES[marker], ensure_ascii=False).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def serve() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


# ---------------------------------------------------------------- 客户端

def build_request(question: str, case: str, max_tokens: int = 64) -> dict:
    """客户端发出的请求体。四个部分是分开的。"""
    return {
        # 1. 消息：调用方决定放什么进去
        "messages": [
            {"role": "system", "content": "你是退货政策助手，只回答与退货相关的政策。"},
            {"role": "user", "content": question},
        ],
        # 2. 采样参数：调用方决定怎么从分布里取
        "temperature": 0.0,
        "top_p": 1.0,
        # 3. 输出上限：调用方决定最多生成多少
        "max_tokens": max_tokens,
        # 4. （本例用）告诉服务端返回哪种响应
        "metadata": {"case": case},
    }


def call(port: int, request: dict) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(request, ensure_ascii=False).encode()
    conn.request("POST", "/v1/chat/completions", payload,
                 {"Content-Type": "application/json"})
    response = conn.getresponse()
    data = json.loads(response.read())
    conn.close()
    return data


# ---------------------------------------------------------------- 演示

def main() -> None:
    server, port = serve()
    try:
        question = "能退吗？"

        print("=" * 66)
        print("请求体（调用方构造）")
        print("=" * 66)
        print(json.dumps(build_request(question, "normal"), ensure_ascii=False, indent=2))

        for case in ("normal", "truncated", "tool", "filtered"):
            request = build_request(question, case)
            response = call(port, request)

            print()
            print("=" * 66)
            print(f"响应体（case={case}）")
            print("=" * 66)
            print(json.dumps(response, ensure_ascii=False, indent=2))

            choice = response["choices"][0]
            message = choice["message"]
            print()
            print(f"  finish_reason : {choice['finish_reason']}")
            print(f"  content       : {message.get('content')!r}")
            print(f"  tool_calls    : {message.get('tool_calls')}")
            print(f"  usage         : {response['usage']}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
