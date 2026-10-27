"""校验失败之后：把 pydantic 的错误结构回灌给模型。

运行：python code/knowledge/ch05_pydantic/error_feedback.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import BaseModel, ValidationError

from fake_server import chat_completion, client_for, scripted_server


class Verdict(BaseModel):
    eligible: bool
    reason: str


def to_feedback(exc: ValidationError) -> str:
    """把错误列表压成一段模型能读的提示，不夹带 Python 堆栈。"""
    lines = ["你上一次的输出不合法，请只输出 JSON 对象，字段如下："]
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"])
        lines.append(f"- {field}: {err['msg']}（你给的是 {err['input']!r}）")
    return "\n".join(lines)


def respond(index, body):
    if index == 0:
        return chat_completion('{"eligible": "true", "reason": 123}', usage=(40, 12))
    return chat_completion('{"eligible": true, "reason": "未拆封"}', usage=(70, 10))


def ask(client, messages):
    reply = client.chat.completions.create(
        model="demo-model",
        messages=messages,
        response_format={"type": "json_object"},
    )
    return reply.choices[0].message.content


with scripted_server(respond) as base_url:
    client = client_for(base_url)
    messages = [{"role": "user", "content": "订单 A1001 能否退货？只输出 JSON。"}]

    for attempt in range(1, 3):
        raw = ask(client, messages)
        print(f"第 {attempt} 次返回：{raw}")
        try:
            verdict = Verdict.model_validate_json(raw)
        except ValidationError as exc:
            feedback = to_feedback(exc)
            print("校验失败，回灌这段：")
            print(feedback)
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": feedback},
            ]
            continue
        print("通过：", verdict)
        break
