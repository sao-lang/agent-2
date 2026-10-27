"""同一个问题，三种请求，三种响应。

问题固定为"杭州现在天气怎么样"。三种情况只改一处：请求里有没有 `tools`。
服务端是 `fake_server` 的脚本化实现，按请求体里有没有 `tools` 决定回放哪种响应；
**响应文本是写死的，不是模型输出**，它只用来固定 JSON 形状。

换成真实服务时，把 `client_for(base_url)` 换成
`OpenAI(api_key=..., base_url=...)`，其余代码不动。
"""

from __future__ import annotations

from fake_server import chat_completion, client_for, scripted_server
from tools import SYSTEM, WEATHER_TOOL, tool_call


def respond(index: int, body: dict) -> dict:
    """按请求体决定回哪一种：没有 tools 就编，有 tools 就给动作。"""
    if not body.get("tools"):
        return chat_completion(
            content="杭州今天多云转晴，最高气温 24°C。",
            finish_reason="stop",
            usage=(41, 12),
        )
    return chat_completion(
        content=None,
        tool_calls=[tool_call("get_weather", {"city": "杭州"}, "call_weather_01")],
        finish_reason="tool_calls",
        usage=(88, 15),
    )


def ask(text: str, tools: list[dict] | None = None):
    """发一次请求，返回 openai SDK 的响应对象本身。"""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": text},
    ]
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        kwargs: dict = {"model": "demo-model-2024", "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return client.chat.completions.create(**kwargs)


if __name__ == "__main__":
    cases = [
        ("① 没有 tools", "杭州现在天气怎么样？", None),
        ("② 没有 tools，提示词里写明'不要编造'",
         "杭州现在天气怎么样？\n如果你不知道，直接说你不知道，不要编造。", None),
        ("③ 有 tools", "杭州现在天气怎么样？", [WEATHER_TOOL]),
    ]
    for label, text, tools in cases:
        resp = ask(text, tools)
        choice = resp.choices[0]
        print(f"{label}：")
        print(f"   + content={choice.message.content!r}")
        print(f"   + finish_reason={choice.finish_reason}")
        for call in choice.message.tool_calls or []:
            print(f"   + tool_call id={call.id}  name={call.function.name}")
            print(f"     arguments={call.function.arguments!r}"
                  f"  类型={type(call.function.arguments).__name__}")
        print()
