"""第 44 章 step1：输出解析器——把"模型说的话"变成程序能用的数据（离线）。

运行：
    python code/framework/lc/ch44/step1_parsers.py

上一级的痛点：
    模型的输出是自然语言。你不能对一段话做 sum()，也不能把它塞进数据库。

这一级做什么：
    ① 五种常见输出，看有多少能直接 json.loads
    ② 三种解析器逐级加严：Str / Json / Pydantic
    ③ Pydantic 校验失败长什么样（这是最重要的一段）
    ④ with_structured_output 和"解析器"的关系

看完你要能回答：
    输出不稳定时，该在哪一层兜底——提示词、解析器、还是校验重试？
"""
from __future__ import annotations

import json
from typing import Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import (
    JsonOutputParser,
    PydanticOutputParser,
    StrOutputParser,
)
from pydantic import BaseModel, Field


class Refund(BaseModel):
    """退款判定结果。字段少而硬，是让模型"必须给出结构化答案"的关键。"""

    decision: Literal["可退", "不可退", "需人工"]
    days_used: int = Field(description="已使用天数")
    reason: str = Field(max_length=60, description="一句话结论依据")


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


SAMPLES = [
    '{"decision": "可退", "days_used": 3, "reason": "7 天无理由"}',
    "```json\n{\"decision\": \"可退\", \"days_used\": 3, \"reason\": \"7 天无理由\"}\n```",
    "判定结果如下：\n{\"decision\": \"可退\", \"days_used\": 3, \"reason\": \"7 天无理由\"}",
    "decision: 可退, days_used: 3",
    "我认为可以退。",
]


def main() -> None:
    line("① 五种真实输出，能直接 json.loads 的有几个？")
    ok = 0
    for i, s in enumerate(SAMPLES, 1):
        try:
            json.loads(s)
            ok += 1
            print(f"  {i}. ✓ 能解析   {s[:50]!r}")
        except json.JSONDecodeError:
            print(f"  {i}. ✗ 不能解析 {s[:50]!r}")
    print(f"\n  → {ok}/{len(SAMPLES)} 能直接解析。这就是「解析器」存在的理由。")

    line("② 三个解析器：Str / Json / Pydantic")
    text = SAMPLES[1]

    print(f"  StrOutputParser      → {StrOutputParser().parse(text)[:30]!r}")
    print("                          （只是把 content 原样拿出来，不做校验）")

    try:
        print(f"  JsonOutputParser     → {JsonOutputParser().parse(text)}")
        print("                          （能从 ```json 代码块里抠出 JSON）")
    except OutputParserException as e:
        print(f"  JsonOutputParser     → 失败：{e}")

    p = PydanticOutputParser(pydantic_object=Refund)
    parsed = p.parse(text)
    print(f"  PydanticOutputParser → {parsed}")
    print(f"                         type = {type(parsed).__name__}")
    print("\n  格式说明（可以直接塞进提示词，让模型照格式答）：")
    print("  " + p.get_format_instructions().replace("\n", "\n  ")[:400])

    line("③ 最重要的一段：Pydantic 校验失败长什么样")

    bad_cases = {
        "枚举值写错": '{"decision": "可以退", "days_used": 3, "reason": "7 天"}',
        "类型写错": '{"decision": "可退", "days_used": "三天", "reason": "7 天"}',
        "少了字段": '{"decision": "可退"}',
    }
    for name, raw in bad_cases.items():
        try:
            p.parse(raw)
            print(f"  {name:<10} → 通过（不该发生）")
        except OutputParserException as e:
            first = str(e).split("\n")[0]
            print(f"  {name:<10} → OutputParserException: {first[:88]}")

    print("\n  → 解析器不「修」数据，它只是把错误提前到你能看到的地方。")

    line("④ 校验失败之后怎么办：带错误信息重试（离线模拟）")

    def call_model(attempt: int) -> str:
        # 第 1 次：模型"自作主张"改了枚举值；第 2 次：看到报错后改对
        if attempt == 1:
            return '{"decision": "可以退", "days_used": 3, "reason": "7 天无理由"}'
        return '{"decision": "可退", "days_used": 3, "reason": "7 天无理由"}'

    def parse_with_repair(max_try: int = 2) -> Refund:
        prompt_extra = ""
        for attempt in range(1, max_try + 1):
            raw = call_model(attempt)
            try:
                return p.parse(raw)
            except OutputParserException as e:
                prompt_extra = f"上次输出不合法：{str(e).splitlines()[0]}"
                print(f"    第 {attempt} 次失败 → 反馈给模型：{prompt_extra[:60]}")
        raise RuntimeError("两次都没修好")

    result = parse_with_repair()
    print(f"  最终结果 = {result}")
    print("  → 代价：多一次调用。收益：把 25% 的失败率降到接近 0（第 6 章实测 25%→75%）")

    line("⑤ with_structured_output：先看它和解析器的关系")
    print("  它不是新东西，等价于：")
    print("    model.bind_tools([schema], tool_choice=schema.__name__)  →  读 tool_calls[0].args")
    print("  也就是「让模型以工具调用形式返回 JSON」+「自动帮你看字段」。")
    print("  好处：没有「正文里夹一段 JSON」的解析风险。")
    print("  代价：仍是模型输出，仍可能违反 schema —— 仍需校验重试。")


if __name__ == "__main__":
    main()
