"""流式响应里的收尾：finish_reason 不在正文那一块。

`stream=True` 时一次调用被拆成多个 chunk。正文分散在 `delta.content` 里，
`finish_reason` 只出现在最后那个空 delta 上，`usage` 还要额外要求才带回来。

响应由脚本化后端按 SSE 格式回放，不是模型输出。
"""

from __future__ import annotations

from fake_server import client_for, scripted_server

QUESTION = "能退吗？"

PIECES = [
    {"role": "assistant", "content": "签收后"},
    {"content": " 7 天内"},
    {"content": "可退。"},
]


def respond(index: int, body: dict) -> dict:
    """拼一份 SSE 响应体：三个正文块 + 一个只带收尾原因的块。"""
    sse = [
        {"id": "chatcmpl-demo", "object": "chat.completion.chunk", "created": 0,
         "model": "demo-model",
         "choices": [{"index": 0, "delta": piece, "finish_reason": None}]}
        for piece in PIECES
    ]
    sse.append({
        "id": "chatcmpl-demo", "object": "chat.completion.chunk", "created": 0,
        "model": "demo-model",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 24, "completion_tokens": 6, "total_tokens": 30},
    })
    return {"_sse": sse}


def main() -> None:
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        stream = client.chat.completions.create(
            model="demo-model",
            messages=[{"role": "user", "content": QUESTION}],
            temperature=0.0,
            max_tokens=64,
            stream=True,
            stream_options={"include_usage": True},
        )

        parts: list[str] = []
        reason = None
        for i, chunk in enumerate(stream):
            choice = chunk.choices[0]
            if choice.delta.content:
                parts.append(choice.delta.content)
            else:
                reason = choice.finish_reason
            print(f"  chunk {i}: delta={choice.delta.content!r:<12}"
                  f"finish_reason={choice.finish_reason!r:<8}usage={'有' if chunk.usage else 'None'}")

    print()
    print(f"拼接后的文本：{''.join(parts)!r}")
    print(f"收尾原因：{reason!r}")
    print("正文分在三块里，第四块的 delta 是空的，只带收尾原因与用量。")


if __name__ == "__main__":
    main()
