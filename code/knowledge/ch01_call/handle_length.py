"""length 的三种补法，全部走真实 SDK 往返。

三次请求都由 `openai` 客户端发出，`max_tokens`、`messages` 的差异体现在
请求体里；响应对象上的 `finish_reason` 与 `usage` 决定下一步做什么。

回放的是固定响应（截断的一份、完整的一份、续写的一份），不是模型输出。
"""

from __future__ import annotations

from collections import Counter

from fake_server import chat_completion, client_for, scripted_server

QUESTION = "能退吗？"
END_MARKS = ("。", "！", "？")

SCRIPTS = {
    "first": chat_completion("签收后7天内可退，条件", finish_reason="length", usage=(24, 6)),
    "retry": chat_completion("签收后7天内可退，条件是商品未拆封。", finish_reason="stop", usage=(24, 11)),
    "continue": chat_completion("是商品未拆封。", finish_reason="stop", usage=(30, 4)),
}


def respond(index: int, body: dict) -> dict:
    return SCRIPTS[body["case"]]


def cut_at_sentence(text: str) -> str:
    """本地找最后一个句号，丢掉之后的部分。不产生新调用。"""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in END_MARKS:
            return text[: i + 1]
    return ""


def seam_overlap(prefix: str, tail: str, window: int = 6) -> int:
    """续写的接缝检查：尾巴开头有多少字与正文结尾重复。"""
    for k in range(min(window, len(tail), len(prefix)), 0, -1):
        if prefix.endswith(tail[:k]):
            return k
    return 0


def main() -> None:
    calls: Counter = Counter()
    prompt_tokens: Counter = Counter()

    def ask(client, case: str, messages: list[dict], max_tokens: int):
        calls[case] += 1
        response = client.chat.completions.create(
            model="demo-model",
            messages=messages,
            temperature=0.0,
            max_tokens=max_tokens,
            extra_body={"case": case},
        )
        prompt_tokens[case] += response.usage.prompt_tokens
        return response

    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        base = [{"role": "user", "content": QUESTION}]

        # 第一次：上限 6，被截断
        first = ask(client, "first", base, 6)
        truncated = first.choices[0].message.content or ""
        print(f"原始：{truncated!r} ({first.choices[0].finish_reason}, 上限=6)")
        print(f"  completion_tokens={first.usage.completion_tokens}  prompt_tokens={first.usage.prompt_tokens}")
        print()

        # 方案一：本地截到最后一个完整句
        cut = cut_at_sentence(truncated)
        print("方案一 直接截到最后一个完整句：")
        print(f"  {cut!r}  丢弃 {len(truncated) - len(cut)} 个字  调用次数 {calls['first']}")
        print()

        # 方案二：放宽上限，从头重来
        retried = ask(client, "retry", base, 64)
        full = retried.choices[0].message.content or ""
        print("方案二 放宽上限重来：")
        print(f"  {full!r}  ({retried.choices[0].finish_reason})  调用次数 {calls['first'] + calls['retry']}")
        print(f"  新增 {len(full) - len(truncated)} 字，但重算了前面 {len(truncated)} 字的生成")
        print(f"  两次 prompt_tokens 合计 {prompt_tokens['first'] + prompt_tokens['retry']}，输入全文各计一次")
        print()

        # 方案三：把已生成内容作为助手消息，请求接着写
        messages = base + [
            {"role": "assistant", "content": truncated},
            {"role": "user", "content": "接着上面写完，不要重复已经写过的内容。"},
        ]
        cont = ask(client, "continue", messages, 32)
        tail = cont.choices[0].message.content or ""
        joined = truncated + tail
        print("方案三 续写：")
        print(f"  {joined!r}  ({cont.choices[0].finish_reason})  调用次数 {calls['first'] + calls['continue']}")
        print(f"  只补了 {len(tail)} 字，接缝重叠 {seam_overlap(truncated, tail)} 字")
        print(f"  两次 prompt_tokens 合计 {prompt_tokens['first'] + prompt_tokens['continue']}，第二次只多带了已生成的部分")
        print()

        print("对照：")
        print(f"  {'方案':<10}{'调用次数':<10}{'产出字符':<10}{'输入 token 合计':<14}备注")
        for name, count, produced, tokens, note in (
            ("一 截断", 1, len(cut), prompt_tokens["first"], "丢失后半句"),
            ("二 重来", 2, len(full), prompt_tokens["first"] + prompt_tokens["retry"], "整段重算"),
            ("三 续写", 2, len(joined), prompt_tokens["first"] + prompt_tokens["continue"], "需处理接缝"),
        ):
            print(f"  {name:<10}{count:<10}{produced:<10}{tokens:<14}{note}")


if __name__ == "__main__":
    main()
