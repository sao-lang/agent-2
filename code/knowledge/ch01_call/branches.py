"""按 finish_reason 分支：四种取值对应四种动作，第五种落进兜底。

同一批响应对象（真实的 SDK 往返，内容由服务端回放），换成"先看收尾原因"的
写法。下面每个动作都是从 `choices[0].finish_reason` 上分支出来的。

兜底分支是有意设计成"未知"而不是"接受"：新取值应当被人看见。
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

LABELS = {
    "正常": "stop",
    "截断": "length",
    "要调工具": "tool_calls",
    "被过滤": "content_filter",
    "新取值": "unknown_value",
}


def respond(index: int, body: dict) -> dict:
    return SCRIPTS[body["case"]]


def decide(response) -> tuple[str, str]:
    """拿到响应，返回（下一步动作，理由）。最后一支是兜底。"""
    choice = response.choices[0]
    reason = choice.finish_reason

    if reason == "stop":
        return "接受", "文本已完整，直接使用"
    if reason == "length":
        return "续写或重来", "文本被截断，需要续写或放宽上限"
    if reason == "tool_calls":
        names = [c.function.name for c in choice.message.tool_calls or []]
        return "执行工具", f"需要执行 {names}，再回灌结果"
    if reason == "content_filter":
        return "中止", "被内容过滤拦截，重试无效"
    return "未知", f"未处理的取值：{reason}"


def main() -> None:
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        print(f"  {'情况':<6}{'finish_reason':<17}{'动作':<10}理由")
        for label in ("正常", "截断", "要调工具", "被过滤", "新取值"):
            response = client.chat.completions.create(
                model="demo-model",
                messages=[{"role": "user", "content": QUESTION}],
                temperature=0.0,
                max_tokens=6,
                extra_body={"case": label},
            )
            action, why = decide(response)
            print(f"  {label:<6}{LABELS[label]:<17}{action:<10}{why}")


if __name__ == "__main__":
    main()
