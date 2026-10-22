"""第 6 章 step3：把 schema 从 if 地狱变成声明式（离线，依赖 pydantic）。

运行：
    python code/ch06_parse/step3_schema.py

上一级的痛点（step2）：校验能用了，但它是 40 行手写 if。
                     产品说"再加个 urgency 字段（只能是 high/normal）"，
                     你要改 3 处：校验函数、错误提示、文档。

这一级做什么：用 pydantic 声明一次 schema，**校验、错误提示、JSON Schema
             （可以直接塞进 prompt 给模型看）三样东西自动生成**。

关键收益：**同一个 schema 同时是"给模型的说明书"和"给代码的校验器"**，
        这消除了"prompt 里写的格式"和"代码里校验的格式"不一致这个常见 bug。
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


# ============================================================ 声明 schema
class Intent(str, Enum):
    REFUND = "退款"
    RETURN = "退货"
    EXCHANGE = "换货"
    CONSULT = "咨询"


class Urgency(str, Enum):
    HIGH = "high"
    NORMAL = "normal"


class Ticket(BaseModel):
    """一份工单的抽取结果。

    **注意这里没有一行校验代码**——约束全部写在类型和 Field 上。
    """

    order_id: str = Field(
        description="订单号，形如 A12345（1 个大写字母 + 3~6 位数字）",
        pattern=r"^[A-Z]\d{3,6}$",
    )
    problem: str = Field(description="用户描述的问题，一句话，不超过 30 字", max_length=30)
    intent: Intent = Field(description="用户诉求：退款 / 退货 / 换货 / 咨询")
    urgency: Urgency = Field(default=Urgency.NORMAL, description="紧急程度，不明确时填 normal")

    @field_validator("problem")
    @classmethod
    def no_empty_problem(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("问题描述不能为空")
        return v.strip()


# ============================================================ 自动生成的指令
def schema_instruction(model: type[BaseModel]) -> str:
    """把 schema 转成给模型看的说明书。

    这一步是本节的核心价值：**说明书和校验器不再各写一遍。**
    """
    js = model.model_json_schema()

    # 只保留字段名、类型、说明；去掉 $defs 之类的噪音
    lines = []
    for name, prop in js.get("properties", {}).items():
        t = prop.get("type") or prop.get("anyOf", [{}])[0].get("type", "?")
        if "$ref" in prop:
            # 枚举类型：$ref 指向 $defs
            ref = prop["$ref"].split("/")[-1]
            enum_def = js["$defs"][ref]
            t = " | ".join(enum_def.get("enum", []))
        lines.append(f'  "{name}": {t}  // {prop.get("description", "")}')

    required = js.get("required", [])
    return (
        "请严格输出以下 JSON，不要输出任何其它文字：\n"
        "{\n" + ",\n".join(lines) + "\n}\n"
        f"必填字段：{', '.join(required)}"
    )


# ============================================================ 校验
def validate_payload(raw: str) -> tuple[Ticket | None, str]:
    """返回 (对象, 错误说明)。错误说明是**给人看的**，不是堆栈。"""
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"不是合法 JSON：{e.msg}"

    try:
        return Ticket.model_validate(data), ""
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msgs.append(f"{loc}: {err['msg']}（收到 {err.get('input')!r}）")
        return None, "；".join(msgs)


# ============================================================ 样本
SAMPLES = [
    ('{"order_id":"A12345","problem":"右耳没声音","intent":"退款","urgency":"high"}', "完全合法"),
    ('{"order_id":"A12345","problem":"右耳没声音","intent":"退款"}', "缺 urgency（有默认值）"),
    ('{"order_id":"A12345","problem":"","intent":"退款"}', "problem 空字符串"),
    ('{"order_id":"A12345","problem":"右耳没声音，我想要退款但是不知道该走什么流程，麻烦帮我看一下应该怎么办才好","intent":"退款"}', "problem 超 30 字"),
    ('{"order_id":"12345","problem":"右耳没声音","intent":"退款"}', "order_id 少字母"),
    ('{"order_id":"A12345","problem":"右耳没声音","intent":"投诉"}', "intent 不在枚举"),
    ('{"order_id":"A12345","problem":"右耳没声音","intent":"退款","urgency":"urgent"}', "urgency 不在枚举"),
    ('{"order_id":"A12345","problem":"右耳没声音"}', "缺必填 intent"),
    ('{"order_id":12345,"problem":"右耳没声音","intent":"退款"}', "order_id 是数字不是字符串"),
]


def main() -> None:
    print("=" * 96)
    print("声明一次 schema，自动得到三样东西")
    print("=" * 96)
    print(schema_instruction(Ticket))

    print("\n" + "=" * 96)
    print(f"{len(SAMPLES)} 条输出，声明式校验结果")
    print("=" * 96)
    for raw, label in SAMPLES:
        obj, err = validate_payload(raw)
        if obj:
            print(f"  ✅ {label:<26} → {obj.order_id} / {obj.intent.value} / {obj.urgency.value}")
        else:
            print(f"  ❌ {label:<26} → {err}")
    print()

    ok = sum(1 for raw, _ in SAMPLES if validate_payload(raw)[0])
    print(f"  通过 {ok}/{len(SAMPLES)}，失败 {len(SAMPLES) - ok} 条，**每条都给出了具体原因**")

    print("\n" + "=" * 96)
    print("声明式 vs 手写 if：改一个字段要动几处？")
    print("=" * 96)
    print(f"  {'':<28}{'手写 if（step2）':<24}{'声明式（step3）'}")
    print("  " + "-" * 76)
    rows = [
        ("新增字段 urgency", "改校验函数 + 改错误提示 + 改文档（3 处）", "加一行 Field（1 处）"),
        ("枚举加一个值", "改常量集合 + 改错误提示（2 处）", "枚举类加一行（1 处）"),
        ("给模型的格式说明", "手写一段，和校验逻辑**容易不一致**", "`schema_instruction()` 自动生成"),
        ("错误信息格式", "自己拼字符串", "pydantic 自动给字段路径 + 原因"),
        ("嵌套对象", "手写递归（很容易漏）", "定义子模型即可"),
    ]
    for a, b, c in rows:
        print(f"  {a:<28}{b:<24}{c}")
    print("  " + "-" * 76)

    print("\n" + "=" * 96)
    print("这里最容易犯的错：prompt 里写的格式和代码校验的格式不一致")
    print("=" * 96)
    print("  典型症状：")
    print("    prompt 里写「intent 填 退款/退货/换货/咨询」")
    print("    代码里却只认 ['退款','退货','换货']  ← 漏了'咨询'")
    print("    → 模型老老实实填了'咨询'，你的代码判它非法，重试 3 次全失败")
    print()
    print("  声明式的做法：**只维护一处**。")
    print("    `schema_instruction(Ticket)` 生成给模型看的说明")
    print("    `Ticket.model_validate(...)` 校验模型的输出")
    print("    两者都从 `Intent` 这个枚举来 → 不可能不一致")

    print("\n" + "=" * 96)
    print("结论")
    print("=" * 96)
    print("  · 用 pydantic 声明一次，**校验 + 说明 + 错误提示**全部自动。")
    print("  · `schema_instruction()` 是本章的关键技巧：")
    print("    **让 prompt 里的格式要求和代码里的校验规则来自同一个源。**")
    print("  · `Field(pattern=...)` / `max_length` / Enum 比手写 if 更难漏。")
    print("  · 错误信息要能直接告诉用户/日志**哪个字段错了、收到了什么**——")
    print("    pydantic 的 `errors()` 已经给了 `loc` 和 `input`，别再自己拼。")
    print()
    print("  下一级（step4）：把这一整套接进真实调用，并处理「重试几次仍不合法」的情况。")

    # 断言：合法样本必须通过，非法样本必须被拒
    assert validate_payload(SAMPLES[0][0])[0] is not None
    assert validate_payload(SAMPLES[5][0])[0] is None  # intent 越界


if __name__ == "__main__":
    main()
