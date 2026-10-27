"""finish_reason 的四个取值，各走一次真实的 SDK 往返。

同一个问题问四次，脚本化后端每次回放不同的收尾原因。请求和响应都经过
`openai` 客户端，下面打印的每个值都是从响应对象上读出来的：
`choices[0].finish_reason`、`choices[0].message.content`、`usage`。

回放的是固定响应，不是模型输出；换真实服务时把 `client_for` 换掉即可。
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

# 四种收尾各一份回放响应
SCRIPTS = {
    "stop": chat_completion("签收后 7 天内可退。", finish_reason="stop", usage=(24, 9)),
    "length": chat_completion("签收后 7 天内可退，条件是商品", finish_reason="length", usage=(24, 16)),
    "tool_calls": chat_completion(None, tool_calls=TOOL_CALLS, finish_reason="tool_calls", usage=(58, 19)),
    "content_filter": chat_completion("", finish_reason="content_filter", usage=(24, 0)),
}


def respond(index: int, body: dict) -> dict:
    """按请求里的 case 字段回放对应响应。"""
    return SCRIPTS[body["case"]]


def ask(client, case: str):
    """一次完整的往返：请求进、响应对象出。"""
    return client.chat.completions.create(
        model="demo-model",
        messages=[{"role": "user", "content": QUESTION}],
        temperature=0.0,
        max_tokens=64,
        extra_body={"case": case},
    )


def main() -> None:
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        for case in ("stop", "length", "tool_calls", "content_filter"):
            response = ask(client, case)
            choice = response.choices[0]
            usage = response.usage
            print(f"=== case={case} ===")
            print(f"  finish_reason   {choice.finish_reason!r}")
            print(f"  content         {choice.message.content!r}")
            print(f"  tool_calls      {choice.message.tool_calls}")
            print(f"  usage           prompt={usage.prompt_tokens} completion={usage.completion_tokens}")
            print()


if __name__ == "__main__":
    main()
