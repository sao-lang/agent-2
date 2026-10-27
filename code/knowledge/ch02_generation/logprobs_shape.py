"""logprobs 的形状：响应里怎么把候选分布带回来。

请求里带 `logprobs=True` 与 `top_logprobs=N`，服务端就会在响应的
`choices[0].logprobs.content` 里逐个 token 给出"选中了谁、它的对数概率、
以及同一位置另外 N 个候选"。

这里的响应是脚本化后端回放的，概率值是给定常数（原理演示，不是模型实测）。
形状是真的：`openai` 客户端把它解析成 `ChoiceLogprobs` 对象。
"""

from __future__ import annotations

import math

from fake_server import chat_completion, client_for, scripted_server

QUESTION = "退货期限是多久？"

# 三个位置：选中的 token，以及同位置的前 N 个候选（概率是给定的演示值）
POSITIONS = [
    ("7天", [("7天", 0.50), ("7日", 0.22), ("一周", 0.15), ("七天", 0.10), ("3天", 0.03)]),
    ("内", [("内", 0.88), ("之", 0.07), ("以", 0.03), ("后", 0.02)]),
    ("可退", [("可退", 0.71), ("可以退", 0.12), ("能退", 0.08), ("可退货", 0.03), ("可退款", 0.01)]),
]


def logprob_node(token: str, candidates: list[tuple[str, float]]) -> dict:
    """一个位置的 logprobs 节点：选中项 + 候选列表。"""
    chosen = dict(candidates)[token]
    return {
        "token": token,
        "logprob": math.log(chosen),
        "bytes": None,
        "top_logprobs": [
            {"token": t, "logprob": math.log(p), "bytes": None} for t, p in candidates
        ],
    }


def respond(index: int, body: dict) -> dict:
    """回放一份带 logprobs 的响应；请求里没要 logprobs 时给 None。"""
    reply = chat_completion("签收后7天内可退。", finish_reason="stop", usage=(20, 6))
    choice = reply["choices"][0]
    if body.get("logprobs"):
        choice["logprobs"] = {"content": [logprob_node(t, c) for t, c in POSITIONS],
                              "refusal": None}
    else:
        choice["logprobs"] = None
    return reply


def main() -> None:
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        asked = client.chat.completions.create(
            model="demo-model",
            messages=[{"role": "user", "content": QUESTION}],
            temperature=0.0,
            max_tokens=16,
            logprobs=True,
            top_logprobs=5,
        )
        plain = client.chat.completions.create(
            model="demo-model",
            messages=[{"role": "user", "content": QUESTION}],
            temperature=0.0,
            max_tokens=16,
        )

    logprobs = asked.choices[0].logprobs
    print(f"要了 logprobs：{type(logprobs).__name__}，共 {len(logprobs.content)} 个位置")
    print(f"没要 logprobs：{plain.choices[0].logprobs!r}")
    print()

    print(f"  {'位置':<6}{'选中':<8}{'p':<8}{'该位置的候选（top_logprobs=5）':<48}{'候选合计'}")
    for i, node in enumerate(logprobs.content):
        chosen_p = math.exp(node.logprob)
        listed = "  ".join(f"{c.token}:{math.exp(c.logprob):.2f}" for c in node.top_logprobs)
        total = sum(math.exp(c.logprob) for c in node.top_logprobs)
        print(f"  {i:<6}{node.token:<8}{chosen_p:<8.2f}{listed:<48}{total:.2f}")
    print()

    tail = 1.0 - sum(math.exp(c.logprob) for c in logprobs.content[2].top_logprobs)
    print(f"第三个位置的候选合计 0.95，剩下 {tail:.2f} 的尾部没有出现在 top_logprobs 里。")
    print("这 0.05 里有若干更冷的候选，它们各自概率很低，合起来才够补满 1。")


if __name__ == "__main__":
    main()
