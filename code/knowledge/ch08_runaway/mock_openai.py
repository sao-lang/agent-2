"""一个只会照剧本回话的 OpenAI 兼容服务，用来在没有 API key 时验证整条链路。

它实现的是真实协议：POST /v1/chat/completions，返回 choices[].message 与 usage，
参数与真实厂商一致（model、messages、tools、temperature、max_tokens）。
所以 mini_agent.py 的代码不需要为它改一行：把 --base-url 指到这里即可。

    python code/knowledge/ch08_runaway/mock_openai.py --port 8899
    python code/knowledge/ch08_runaway/mini_agent.py --base-url http://127.0.0.1:8899/v1 --api-key sk-mock
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = {
    "conclusion": "不可退",
    "signed_days_ago": 9,
    "window_days": 7,
    "clause": "P-7",
    "shipping_fee": 9.0,
    "next_step": "已过 7 天窗口，如属质量问题请提供照片走质量通道",
}


def tool_call(call_id: str, name: str, arguments: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


STALL_PLAN = [
    (None, [tool_call("d1", "get_order", '{"order_id":"A1002"}')], "tool_calls"),
    (None, [tool_call("d2", "get_order", '{"order_id":"A1002"}')], "tool_calls"),
    (None, [tool_call("d3", "get_order", '{"order_id":"A1002"}')], "tool_calls"),
]

RESULT_PLAN = [
    (None, [tool_call("f1", "check_coupon", '{"order_id":"A1001"}')], "tool_calls"),
    (None, [tool_call("f2", "check_coupon", '{"order_id":"A1002"}')], "tool_calls"),
    (None, [tool_call("f3", "check_coupon", '{"order_id":"B2001"}')], "tool_calls"),
]


def script(step: int) -> dict:
    """按"请求里已经出现过几条 assistant 消息"回放。"""
    plan = ACTIVE_PLAN[min(step, len(ACTIVE_PLAN) - 1)]
    content, calls, finish = plan
    return {"content": content, "tool_calls": calls or None, "finish_reason": finish}


def _good_plan() -> list[tuple]:
    return [
        (None, [tool_call("c1", "get_order", '{"order_id":"A1002"}')], "tool_calls"),
        (None, [tool_call("c2", "get_policy", '{"category":"普通"}')], "tool_calls"),
        # 同一请求换一种写法：请求指纹应当归一后拦下
        (None, [tool_call("c3", "get_order", '{ "order_id" : "A1002" }')], "tool_calls"),
        # 参数不是合法 JSON
        (None, [tool_call("c4", "calc_shipping_fee", '{"order_id":"A1002", weight_kg:1.5}')], "tool_calls"),
        # 业务错误：订单不存在
        (None, [tool_call("c5", "calc_shipping_fee", '{"order_id":"Z9999","weight_kg":1.5}')], "tool_calls"),
        (None, [tool_call("c6", "calc_shipping_fee", '{"order_id":"A1002","weight_kg":1.5}')], "tool_calls"),
        # 长文本：触发单条裁剪
        (None, [tool_call("c7", "get_clause_text", '{"category":"普通"}')], "tool_calls"),
        # 被截断
        ("结论：不可退。依据：签收后第 9 天，", [], "length"),
        # 合法 JSON 但缺字段
        ('{"conclusion":"不可退","clause":"P-7"}', [], "stop"),
        (json.dumps(ANSWER, ensure_ascii=False), [], "stop"),
    ]


PLANS = {"good": _good_plan, "stall": lambda: STALL_PLAN, "result": lambda: RESULT_PLAN}
ACTIVE_PLAN: list[tuple] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        step = sum(1 for m in messages if m.get("role") == "assistant")
        s = script(step)
        calls = s["tool_calls"]

        prompt_tokens = 80 + 20 * step
        completion_tokens = 40 if calls else 25
        payload = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "mock"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": s["content"],
                        "tool_calls": calls,
                    },
                    "finish_reason": s["finish_reason"],
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静音访问日志
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--scenario", default="good", choices=["good", "stall", "result"])
    args = parser.parse_args()

    global ACTIVE_PLAN
    ACTIVE_PLAN = PLANS[args.scenario]()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[MOCK] OpenAI 兼容服务：http://127.0.0.1:{args.port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
