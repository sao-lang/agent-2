"""采样参数真的进了请求体：三档温度下的请求体差异。

三段请求都由 `openai` 客户端发出，脚本化后端把收到的请求体交回来。
所以下面打印的 `temperature`、`top_p`、`logprobs` 是 SDK 编码进 HTTP 请求体的
真实字段，不是本地变量。

后端回放的响应内容三档完全相同：它不采样，只回放固定文本。因此这一节能证明
"参数进了请求"，不能证明"参数改变了输出"——后者的原理在 temperature.py 里。
"""

from __future__ import annotations

import json

from fake_server import chat_completion, client_for, scripted_server

QUESTION = "退货期限是多久？"
TEMPERATURES = (0.0, 0.7, 1.2)
WATCH = ("model", "max_tokens", "temperature", "top_p", "logprobs", "top_logprobs", "stop")

ECHO = chat_completion("签收后 7 天内可申请退货。", finish_reason="stop", usage=(20, 8))


def ask(client, temperature: float):
    """同一提示、同一参数集，只改温度。"""
    return client.chat.completions.create(
        model="demo-model",
        messages=[{"role": "user", "content": QUESTION}],
        temperature=temperature,
        top_p=0.9,
        max_tokens=16,
        logprobs=True,
        top_logprobs=5,
        stop=["\n\n"],
        extra_body={"case": "echo"},
    )


def main() -> None:
    sent: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        sent.append(body)
        return ECHO

    replies: dict[float, str] = {}
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        for temperature in TEMPERATURES:
            response = ask(client, temperature)
            replies[temperature] = response.choices[0].message.content or ""

    bodies = {t: sent[i] for i, t in enumerate(TEMPERATURES)}

    print("一次请求的请求体（节选采样相关字段）")
    print(json.dumps({k: bodies[0.0][k] for k in WATCH if k in bodies[0.0]},
                     ensure_ascii=False, indent=2))
    print()

    print("三档温度下的请求体差异")
    print(f"  {'字段':<14}{'temp=0.0':<11}{'temp=0.7':<11}{'temp=1.2':<11}结论")
    for key in WATCH:
        values = [str(bodies[t].get(key)) for t in TEMPERATURES]
        verdict = "随参数变" if len(set(values)) > 1 else "不变"
        print(f"  {key:<14}{values[0]:<11}{values[1]:<11}{values[2]:<11}{verdict}")
    print()

    print("三档的响应内容（回放，不采样）：")
    for temperature in TEMPERATURES:
        print(f"  temperature={temperature:<5} {replies[temperature]!r}")
    print()
    print("请求体变了，回放的内容没变：这一段能证明参数进了请求，不能证明参数改变了输出。")


if __name__ == "__main__":
    main()
