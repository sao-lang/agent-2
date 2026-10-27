"""同一个问题，三种提示词，三个结果。

问题固定为"杭州现在天气怎么样"。三种情况只改两处：请求里有没有 tools、
工具说明写多细。用来回答一个问题：模型凭什么知道"可以查"，而不是"只能猜"。
"""

from __future__ import annotations

import json

from transport import SYSTEM, WEATHER_TOOL, Transport, speech_to_json

QUESTION = "杭州现在天气怎么样？"


def ask(assembled: str, tools: list[dict] | None = None) -> tuple[str, str]:
    """发一次请求，返回 (content, finish_reason)。assembled 是拼接后的提示词。"""
    request: dict = {
        "model": "demo-model-2024",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": assembled},
        ],
    }
    if tools:
        request["tools"] = tools
    response = Transport().post(request)
    choice = response["choices"][0]
    return choice["message"].get("content") or "", choice["finish_reason"]


def parse_call(reply: dict) -> dict:
    """把 tool_calls[0] 取出来：名字已经是字符串，参数要再解析一次。"""
    call = reply["choices"][0]["message"]["tool_calls"][0]
    return {
        "id": call["id"],
        "name": call["function"]["name"],
        "args": json.loads(call["function"]["arguments"]),
    }


def main() -> None:
    weak = QUESTION

    # 详细版：等价于把工具说明交给 speech_to_json 读一遍，
    # 模型看到的正是这段文字。这里手工写成"读出来的样子"，省得反复调用。
    strong = (
        QUESTION
        + "\n可用工具（只能从这里选）：\n"
        + speech_to_json(
            json.dumps(WEATHER_TOOL["function"], ensure_ascii=False, indent=2)
        )
    )

    print("① 没有 tools，只说问题：")
    content, reason = ask(weak)
    print(f"   content={content!r}")
    print(f"   finish_reason={reason}")

    print()
    print("② 没有 tools，提示词里明确说'不要编'：")
    content, reason = ask(weak + "\n如果你不知道，直接说你不知道，不要编造。")
    print(f"   content={content!r}")
    print(f"   finish_reason={reason}")

    print()
    print("③ 有 tools，说明里写明参数和用途：")
    request = {
        "model": "demo-model-2024",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": strong},
        ],
        "tools": [WEATHER_TOOL],
    }
    transport = Transport()
    reply = transport.post(request)
    choice = reply["choices"][0]
    print(f"   content={choice['message']['content']!r}")
    print(f"   finish_reason={choice['finish_reason']}")
    call = parse_call(reply)
    print(f"   tool_call.name={call['name']}  args={call['args']}")

    print()
    print("③ 的 tool_calls 原文：")
    raw = reply["choices"][0]["message"]["tool_calls"]
    print(json.dumps(raw, ensure_ascii=False, indent=2))

    print()
    print("模型这一步收到的全部内容（请求体）：")
    print(json.dumps(request, ensure_ascii=False, indent=2)[:600], "...")

    print()
    print("三种情况对比：")
    rows = [
        ("没有 tools", "编了一个 24°C", "内容看起来完全合理，无法从文字上分辨真假"),
        ("没有 tools + 禁止编造", "仍然编了一个 24°C", "提示词的'不要'没有对应的动作可选"),
        ("有 tools", "输出了一个动作，没有答案", "内容为 None，要靠调用方执行"),
    ]
    for i, (case, out, why) in enumerate(rows, 1):
        print(f"  {i}. {case:<22} {out:<16} {why}")


if __name__ == "__main__":
    main()
