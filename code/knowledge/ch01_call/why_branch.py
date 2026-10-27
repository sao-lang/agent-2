"""只取 content 的写法：五种结果被压成同一个返回值。

五次请求都经过 `openai` 客户端，响应是 SDK 解析出来的对象，取值由服务端回放
（不是模型输出）。函数只有一行：把 `content` 当答案交出去。

第五种是"厂商新增了一个取值"，用来测这段写法在未知情况下的表现。
"""

from __future__ import annotations

from fake_server import chat_completion, client_for, scripted_server

QUESTION = "能退吗？"

TOOL_CALLS = [
    {
        "id": "call_abc",
        "type": "function",
        "function": {"name": "get_order", "arguments": '{"order_id": "A1001"}'},
    }
]

SCRIPTS = {
    "正常": chat_completion("签收后7天内可退。", finish_reason="stop", usage=(24, 9)),
    "截断": chat_completion("签收后7天内可退，条件是商品", finish_reason="length", usage=(24, 16)),
    "要调工具": chat_completion(None, tool_calls=TOOL_CALLS, finish_reason="tool_calls", usage=(58, 19)),
    "被过滤": chat_completion("", finish_reason="content_filter", usage=(24, 0)),
    "新取值": chat_completion("签收后7天内可退。", finish_reason="unknown_value", usage=(24, 9)),
}


def respond(index: int, body: dict) -> dict:
    return SCRIPTS[body["case"]]


def only_content(response) -> str:
    """第一版写法：把 content 当答案。"""
    return response.choices[0].message.content or ""


def main() -> None:
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        for label in ("正常", "截断", "要调工具", "被过滤", "新取值"):
            response = client.chat.completions.create(
                model="demo-model",
                messages=[{"role": "user", "content": QUESTION}],
                temperature=0.0,
                max_tokens=6,
                extra_body={"case": label},
            )
            text = only_content(response)
            shown = repr(text) if text else "（空字符串）"
            print(f"  {label:<6} -> {shown}")


if __name__ == "__main__":
    main()
