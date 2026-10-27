"""五种把输出变成结构的方法，逐一跑一遍真实的 openai 客户端。

服务端是脚本化的（`fake_server`）：请求照常编码、照常走 HTTP、照常用 SDK 解析，
只有响应体是脚本里写好的。所以下面的"输出"是**脚本回放的内容**，不是模型实测；
它用来固定形状，让每种做法的失败方式可以被逐字看到。

换成真实服务时只改一处：把 client_for(base_url) 换成
OpenAI(base_url="https://api.example.com/v1", api_key=KEY)，其余代码不动。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from fake_server import chat_completion, client_for, scripted_server

SYSTEM = "你是退货客服，只回答退货相关问题，只依据给定政策判断。"
QUESTION = "订单 A1001 签收 3 天、未拆封，能退吗？按 JSON 给出 order_id、days、reason。"

TARGET = {"order_id": str, "days": int, "reason": str}

SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "days": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["order_id", "days", "reason"],
    "additionalProperties": False,
}

TOOL = {
    "type": "function",
    "function": {
        "name": "submit_result",
        "description": "提交退货资格判断结果",
        "parameters": SCHEMA,
    },
}

STRICT_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "refund_check", "strict": True, "schema": SCHEMA},
}

GOOD = '{"order_id": "A1001", "days": 7, "reason": "签收不想要"}'


class Result(BaseModel):
    """做法五用的模型：三层校验写进类型与约束里。"""

    order_id: str = Field(min_length=1)
    days: int = Field(ge=1, le=90)
    reason: str = Field(max_length=40)


@dataclass
class Outcome:
    name: str
    syntax: str
    fields: str
    verdict: str
    retries: int


def messages() -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": QUESTION},
    ]


def feedback(bad: str, error: str) -> list[dict]:
    """把具体的失败原因回灌，而不是只说"重来一次"。"""
    return messages() + [
        {"role": "assistant", "content": bad},
        {"role": "user", "content": f"上面的输出有问题：{error}。请修正后重新输出，只给 JSON。"},
    ]


def validate(obj: dict | None) -> str | None:
    """三层校验：有没有对象、字段齐不齐、类型对不对，最后看取值范围。"""
    if obj is None:
        return "没有解析出对象"

    missing = [k for k in TARGET if k not in obj]
    if missing:
        return f"缺字段 {missing}"

    wrong = [k for k, t in TARGET.items() if not isinstance(obj[k], t)]
    if wrong:
        return f"类型不对 {wrong}"

    if not (1 <= obj["days"] <= 90):
        return f"days={obj['days']} 超出 1-90"
    return None


# ---------------------------------------------------------------- 各做法的单次调用


def plain_text(client, msgs: list[dict]) -> str:
    """纯文本调用：不带任何格式约束，返回原始回复。"""
    return client.chat.completions.create(
        model="demo-model", messages=msgs).choices[0].message.content or ""


def plain_extract(text: str) -> tuple[dict | None, str | None]:
    """做法一的解析：用正则把 JSON 片段捞出来。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, "没有找到 JSON 片段"
    try:
        return json.loads(m.group(0)), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


def json_text(client, msgs: list[dict]) -> str:
    """JSON mode 的原始回复：服务端保证语法合法，字段名不保证。"""
    return client.chat.completions.create(
        model="demo-model", messages=msgs,
        response_format={"type": "json_object"}).choices[0].message.content or ""


def json_obj(client, msgs: list[dict]) -> dict:
    """JSON mode + 本地解析：语法已经被服务端保证了。"""
    return json.loads(json_text(client, msgs))


def tool_submit(client) -> tuple[str, str]:
    """function calling：强制调用 submit_result，返回 (arguments, finish_reason)。"""
    reply = client.chat.completions.create(
        model="demo-model", messages=messages(), tools=[TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_result"}})
    choice = reply.choices[0]
    return choice.message.tool_calls[0].function.arguments, choice.finish_reason


def strict_text(client) -> str:
    """严格模式：服务端按 schema 约束采样，返回原始回复。"""
    return client.chat.completions.create(
        model="demo-model", messages=messages(),
        response_format=STRICT_FORMAT).choices[0].message.content or ""


def pydantic_error(text: str) -> str | None:
    """pydantic 校验：通过返回 None，不通过返回错误原文。"""
    try:
        Result.model_validate_json(text)
        return None
    except ValidationError as e:
        return str(e)


def heal(client, msgs: list[dict]) -> tuple[Result | None, int]:
    """自愈重试：把 pydantic 的错误原文当成下一条消息回灌。"""
    history = list(msgs)
    for attempt in range(3):
        text = json_text(client, history)
        error = pydantic_error(text)
        print(f"第 {attempt + 1} 次尝试：\n  原始回复：{text!r}")
        if error is None:
            print(f"  校验：通过 {Result.model_validate_json(text)}")
            return Result.model_validate_json(text), attempt
        print(f"  pydantic：{error.splitlines()[0]}")
        for line in error.splitlines()[1:]:
            print(f"  {line}")
        history = history + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"上面的输出有问题：{error}。请修正后重新输出，只给 JSON。"},
        ]
    return None, 3


# ---------------------------------------------------------------- 五种做法


def approach_plain() -> Outcome:
    print("=" * 78)
    print("做法一：纯文本 + 正则")
    print("=" * 78)
    bad = '{“order_id”: “A1001”, “days”: 7, “reason”: “签收不想要”}'
    replies = [bad, GOOD]

    def respond(index: int, body: dict) -> dict:
        return chat_completion(content=replies[min(index, 1)],
                               usage=(len(body["messages"]) * 20, 24))

    retries = 0
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        text = plain_text(client, messages())
        print(f"第一次尝试：\n  原始回复：{text!r}")
        obj, err = plain_extract(text)
        print(f"  抽取结果：{obj if obj else err}")

        while obj is None and retries < 2:
            retries += 1
            text = plain_text(client, feedback(text, err or ""))
            obj, err = plain_extract(text)
            print(f"回灌错误后第 {retries} 次重试：\n  原始回复：{text!r}")
            print(f"  抽取结果：{obj if obj else err}")

    error = validate(obj)
    print(f"  校验：{error or '通过'}")
    return Outcome("纯文本+正则", "不合法", "未通过",
                   "重试后通过" if not error else "重试无效", retries)


def approach_json_mode() -> Outcome:
    print("=" * 78)
    print("做法二：JSON mode")
    print("=" * 78)
    reply = '{"orderId": "A1001", "days": 7, "reason": "签收不想要"}'

    def respond(index: int, body: dict) -> dict:
        return chat_completion(content=reply, usage=(len(body["messages"]) * 20, 26))

    retries = 0
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        text = json_text(client, messages())
        print(f"第一次尝试：\n  原始回复：{text!r}")
        obj = json.loads(text)
        print("  语法：合法，json_object 的承诺兑现了")
        error = validate(obj)
        print(f"  校验：{error}")

        while retries < 2:
            retries += 1
            text = json_text(client, feedback(text, error or ""))
            obj = json.loads(text)
            error = validate(obj)
            print(f"第 {retries} 次重试：\n  原始回复：{text!r}")
            print(f"  校验：{error}")

    return Outcome("JSON mode", "合法", "不通过" if error else "通过",
                   "字段名靠理解" if error else "通过", retries)


def approach_function_call() -> Outcome:
    print("=" * 78)
    print("做法三：function calling，tool_choice 强制调用")
    print("=" * 78)

    def respond(index: int, body: dict) -> dict:
        args = ('{"order_id": "A1001", "days": 7, "reason": "签收不想要"}' if index == 0
                else '{"order_id": "A1001", days: 7}')
        return chat_completion(
            content="", finish_reason="tool_calls",
            tool_calls=[{"id": f"call_{index}", "type": "function",
                         "function": {"name": "submit_result", "arguments": args}}],
            usage=(len(body["messages"]) * 20, 20))

    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        for label in ("正常形状", "arguments 坏掉"):
            arguments, reason = tool_submit(client)
            print(f"{label}：\n  finish_reason={reason}")
            print(f"  arguments={arguments!r}")
            try:
                obj = json.loads(arguments)
                print(f"  解析结果：{obj}")
                print(f"  校验：{validate(obj) or '通过'}")
            except json.JSONDecodeError as e:
                print(f"  解析结果：JSON 解析失败：{e}")
                print("  校验：无法进行")

    return Outcome("function calling", "合法", "通过", "字段由 schema 定", 0)


def approach_strict() -> Outcome:
    print("=" * 78)
    print("做法四：JSON Schema 严格模式")
    print("=" * 78)
    replies = [GOOD, '{"order_id": "A1001", "days": null, "reason": "签收时间未知"}']

    def respond(index: int, body: dict) -> dict:
        return chat_completion(content=replies[index],
                               usage=(len(body["messages"]) * 20, 22))

    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        for label in ("字段齐、类型对", "可选字段被逼成 null"):
            text = strict_text(client)
            obj = json.loads(text)
            print(f"{label}：\n  原始回复：{text!r}")
            print("  语法：合法")
            print(f"  校验：{validate(obj) or '通过'}")

    return Outcome("JSON Schema 严格模式", "合法", "通过", "结构有保证，值要另查", 0)


def approach_self_heal() -> Outcome:
    print("=" * 78)
    print("做法五：本地校验 + 自愈重试（pydantic）")
    print("=" * 78)
    replies = ['{"order_id": "A1001", "days": "三天", "reason": "签收三天"}', GOOD]

    def respond(index: int, body: dict) -> dict:
        return chat_completion(content=replies[min(index, 1)],
                               usage=(len(body["messages"]) * 20, 22))

    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        result, retries = heal(client, messages())

    return Outcome("本地校验+自愈重试", "合法", "通过",
                   "一次失败一次成功" if result else "三次仍失败", retries)


def pad(text: str, width: int) -> str:
    """按显示宽度左对齐：一个汉字占两格。"""
    shown = sum(2 if ord(ch) > 127 else 1 for ch in text)
    return text + " " * max(0, width - shown)


def summary(outcomes: list[Outcome]) -> None:
    print("=" * 78)
    print("五种做法对照（同一份输入）")
    print("=" * 78)
    print(pad("做法", 24) + pad("语法", 10) + pad("字段", 12) + pad("结论", 22) + "重试")
    print("-" * 78)
    for o in outcomes:
        print(pad(o.name, 24) + pad(o.syntax, 10) + pad(o.fields, 12)
              + pad(o.verdict, 22) + str(o.retries))


def request_tokens() -> None:
    """同一份 messages，四种请求体各有多少 token。

    按"请求体 JSON 序列化后"的 token 数算，是成本的近似：真实计费口径由服务端
    决定（它会把 schema 转写成自己认识的形式），但差值的方向与量级在这里能看清。
    """
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    base = {"model": "demo-model", "messages": messages()}
    variants = {
        "纯文本": base,
        "JSON mode": {**base, "response_format": {"type": "json_object"}},
        "function calling": {**base, "tools": [TOOL],
                             "tool_choice": {"type": "function",
                                             "function": {"name": "submit_result"}}},
        "严格模式": {**base, "response_format": STRICT_FORMAT},
    }

    print("=" * 78)
    print("同一份 messages，四种请求体的 token 数")
    print("=" * 78)
    base_n = len(enc.encode(json.dumps(base, ensure_ascii=False)))
    for name, body in variants.items():
        n = len(enc.encode(json.dumps(body, ensure_ascii=False)))
        print(f"  {pad(name, 18)}{n:>5} token   相对纯文本 {n - base_n:+d}")
    print(f"  （messages 本身 {base_n} token，差出来的部分是格式声明）")


def main() -> None:
    outcomes = [
        approach_plain(),
        approach_json_mode(),
        approach_function_call(),
        approach_strict(),
        approach_self_heal(),
    ]
    print()
    request_tokens()
    print()
    summary(outcomes)


if __name__ == "__main__":
    main()
