"""五种结构化输出的做法，逐一实现并对比。

不联网。用一个脚本化的假后端模拟"模型会返回什么"。
每种做法都跑同一批输入，记录语法是否合法、字段是否齐全、是否需要重试。

假后端的输出是按真实接口形态手工构造的，不是模型实测。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 目标结构

TARGET_FIELDS = {"order_id": str, "days": int, "reason": str}


@dataclass
class Outcome:
    name: str
    ok: bool
    parsed: dict | None
    error: str | None
    retries: int


# ---------------------------------------------------------------- 假后端

def fake_reply(style: str, attempt: int = 1) -> str:
    """按不同的输出形态返回文本。attempt>1 时返回更规矩的版本（模拟重试有效）。"""
    if style == "plain":
        # 纯文本：第一次用了非标准引号，JSON 解析会失败；重试后改用标准引号
        if attempt == 1:
            return (
                "好的，我为您查询到了结果：\n\n"
                '```json\n{“order_id”: “A1001”, “days”: 7, “reason”: “签收不想要”}\n```\n\n'
                "如需进一步处理请告知。"
            )
        return (
            "结果如下：\n"
            '{"order_id": "A1001", "days": 7, "reason": "签收不想要"}'
        )

    if style == "json_mode":
        # 语法合法，但字段名写错了
        return json.dumps(
            {"orderId": "A1001", "days": 7, "reason": "签收不想要"},
            ensure_ascii=False,
        )

    if style == "function_call":
        # 通过工具调用返回，参数是 JSON 字符串
        return json.dumps(
            {"name": "submit_result",
             "arguments": json.dumps({"order_id": "A1001", "days": 7, "reason": "签收不想要"},
                                     ensure_ascii=False)},
            ensure_ascii=False,
        )

    if style == "schema":
        # 服务端按 schema 约束，字段名和类型都正确
        return json.dumps(
            {"order_id": "A1001", "days": 7, "reason": "签收不想要"},
            ensure_ascii=False,
        )

    raise ValueError(style)


# ---------------------------------------------------------------- 五种做法

def plain_extract(text: str) -> tuple[dict | None, str | None]:
    """纯文本 + 正则抽取。"""
    m = re.search(r"\{.*?\}", text, re.S)
    if not m:
        return None, "没有找到 JSON 片段"
    try:
        return json.loads(m.group(0)), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


def json_mode_extract(text: str) -> tuple[dict | None, str | None]:
    """JSON mode：服务端保证语法合法。"""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


def function_call_extract(text: str) -> tuple[dict | None, str | None]:
    """function calling：参数是嵌在 JSON 里的字符串，需要二次解析。"""
    try:
        wrapper = json.loads(text)
        return json.loads(wrapper["arguments"]), None
    except (json.JSONDecodeError, KeyError) as e:
        return None, f"解析失败：{e}"


def schema_extract(text: str) -> tuple[dict | None, str | None]:
    """Structured Outputs：服务端按 schema 生成。"""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


def validate(obj: dict | None) -> str | None:
    """字段校验：缺字段、类型不对都算失败。"""
    if obj is None:
        return "无对象"
    missing = [k for k in TARGET_FIELDS if k not in obj]
    if missing:
        return f"缺字段：{missing}"
    wrong = [k for k, t in TARGET_FIELDS.items() if not isinstance(obj[k], t)]
    if wrong:
        return f"类型不对：{wrong}"
    return None


def with_retry(name, extract_fn, style, max_retry: int = 1) -> Outcome:
    """本地校验失败时，把错误回灌重试。"""
    retries = 0
    last_err = None
    for attempt in range(1, max_retry + 2):
        text = fake_reply(style, attempt)
        obj, err = extract_fn(text)
        if err is None:
            err = validate(obj)
        if err is None:
            return Outcome(name, True, obj, None, retries)
        last_err = err
        retries = attempt
    return Outcome(name, False, None, last_err, retries)


def once(name, extract_fn, style) -> Outcome:
    """不重试，只跑一次。"""
    text = fake_reply(style, 1)
    obj, err = extract_fn(text)
    if err is None:
        err = validate(obj)
    return Outcome(name, err is None, obj, err, 0)


# ---------------------------------------------------------------- 演示

def main() -> None:
    cases = [
        ("纯文本+正则", plain_extract, "plain"),
        ("JSON mode", json_mode_extract, "json_mode"),
        ("function calling", function_call_extract, "function_call"),
        ("Structured Outputs", schema_extract, "schema"),
    ]

    print("单次尝试（不重试）：")
    print(f"{'做法':<20}{'语法':<8}{'字段':<8}{'结果'}")
    print("-" * 76)
    for name, fn, style in cases:
        o = once(name, fn, style)
        syntax = "合法" if o.parsed is not None or (o.error and "缺字段" in o.error) else "失败"
        field_ok = "齐全" if o.ok else (o.error or "")
        print(f"{name:<20}{syntax:<8}{'通过' if o.ok else '不通过':<8}{field_ok}")

    print()
    print("加上本地校验与重试：")
    print(f"{'做法':<20}{'结果':<8}{'重试次数':<10}{'说明'}")
    print("-" * 76)
    for name, fn, style in cases:
        o = with_retry(name, fn, style)
        print(f"{name:<20}{'通过' if o.ok else '不通过':<8}{o.retries:<10}{o.error or '一次通过'}")

    print()
    print("要看清的两件事：")
    print("  1. JSON mode 保证了语法，但没保证字段名 —— 上面它返回的是 orderId，")
    print("     重试两次仍然是 orderId，因为模型对字段名的理解没有变。")
    print("     这就是'语法合法'与'结构正确'的区别。")
    print("  2. 纯文本+正则这次靠重试通过了，但重试能成功是因为第二次恰好用了标准引号。")
    print("     这不是保证 —— 同一段逻辑换一批输入，失败率会变化。")


if __name__ == "__main__":
    main()
