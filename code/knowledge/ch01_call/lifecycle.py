"""一次调用里，每个字段由谁产生。

这里用的是真实的 `openai` 客户端：请求由 SDK 编码，响应由 SDK 解析，
输出里的 `response` 就是 `openai.types.chat.ChatCompletion` 对象。

后端起在本地（`fake_server.scripted_server`），按脚本回放 OpenAI 兼容响应。
它保证"请求 → HTTP → 响应 → 对象"这条链是真的，但不产生模型输出。
换真实服务只改 `client_for(...)` 那一处：`OpenAI(base_url=..., api_key=...)`。
"""

from __future__ import annotations

import json

from fake_server import chat_completion, client_for, scripted_server

QUESTION = "能退吗？"


def field_owner(body: dict, response) -> list[tuple[str, str, str]]:
    """把一次调用里真正出现的字段列出来，标注它由谁产生。"""
    choice = response.choices[0]
    usage = response.usage
    return [
        ("messages", f"{len(body['messages'])} 条", "调用方"),
        ("temperature", repr(body.get("temperature")), "调用方"),
        ("max_tokens", repr(body.get("max_tokens")), "调用方"),
        ("finish_reason", choice.finish_reason, "服务端"),
        ("usage", f"{usage.prompt_tokens}+{usage.completion_tokens}={usage.total_tokens}", "服务端"),
    ]


def main() -> None:
    sent: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        sent.append(body)
        return chat_completion("签收后 7 天内可退。", usage=(24, 9))

    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        response = client.chat.completions.create(
            model="demo-model",
            messages=[
                {"role": "system", "content": "你是退货政策助手，只回答与退货相关的政策。"},
                {"role": "user", "content": QUESTION},
            ],
            temperature=0.0,
            max_tokens=64,
            extra_body={"case": "normal"},
        )

    print("请求体（SDK 发出去的原文）")
    print(json.dumps(sent[0], ensure_ascii=False, indent=2))
    print()
    print("响应对象（response.model_dump()）")
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))
    print()
    print("字段归属")
    print("-" * 46)
    for name, value, owner in field_owner(sent[0], response):
        print(f"  {name:<14}{value:<20}{owner}")
    print()
    print(f"choices[0].message.content = {response.choices[0].message.content!r}")
    print(f"choices[0].finish_reason   = {response.choices[0].finish_reason!r}")
    print(f"usage.prompt_tokens        = {response.usage.prompt_tokens}")
    print()
    print("客户端默认值（不在请求体里，只在客户端对象上）")
    print(f"  max_retries  {client.max_retries}")
    print(f"  timeout      {client.timeout}")


if __name__ == "__main__":
    main()
