"""pydantic 常用面：一张清单跑完，每个小节都能单独抄走。

覆盖：别名与命名风格、RootModel、两级校验器与上下文、序列化器与计算字段、
赋值校验与跳过校验、严格类型与 Json、动态模型与泛型、复制与裁剪、
以及给厂商严格模式用的 schema 收拾。
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Generic, TypeVar

from pydantic import (AliasChoices, BaseModel, ConfigDict, Field, Json,
                      RootModel, TypeAdapter, ValidationError, ValidationInfo,
                      computed_field, create_model, field_serializer,
                      field_validator, model_validator)


# ── 1. 别名：对外一种名字，对内另一种
class OrderIn(BaseModel):
    model_config = ConfigDict(alias_generator=lambda s: s.upper(), populate_by_name=True)

    order_id: str
    days: int = Field(ge=0, validation_alias=AliasChoices("days", "signed_days"))


def demo_alias() -> None:
    print("=== 1. 别名与命名风格 ===")
    o = OrderIn.model_validate({"ORDER_ID": "A1001", "signed_days": 3})
    print("  按别名收   ：", o)
    print("  dump 用别名：", o.model_dump(by_alias=True))
    print("  dump 用字段名：", o.model_dump())


# ── 2. RootModel：顶层不是对象
class Tags(RootModel[list[str]]):
    pass


def demo_root() -> None:
    print("=== 2. RootModel ===")
    t = Tags.model_validate(["退货", "七天"])
    print("  根值    ：", t.root)
    print("  dump    ：", t.model_dump())


# ── 3. 两级校验器与上下文
class Refund(BaseModel):
    days: int
    window: int = 7

    @field_validator("days", mode="before")
    @classmethod
    def strip_unit(cls, v: object) -> object:
        if isinstance(v, str) and v.endswith("天"):
            return int(v[:-1])
        return v

    @field_validator("days")
    @classmethod
    def not_negative(cls, v: int, info: ValidationInfo) -> int:
        if v < 0:
            raise ValueError(f"{info.field_name} 不能为负")
        return v

    @model_validator(mode="before")
    @classmethod
    def fill_window(cls, data: object, info: ValidationInfo) -> object:
        ctx = info.context or {}
        if isinstance(data, dict) and "window" not in data and "window" in ctx:
            return {**data, "window": ctx["window"]}
        return data

    @model_validator(mode="after")
    def within_window(self):
        if self.days > self.window:
            raise ValueError(f"{self.days} 天超出窗口 {self.window} 天")
        return self


def demo_validators() -> None:
    print("=== 3. 两级校验器 ===")
    print("  before 去单位 ：", Refund.model_validate({"days": "3天"}))
    print("  上下文补窗口  ：", Refund.model_validate({"days": 30}, context={"window": 60}))
    try:
        Refund.model_validate({"days": 30, "window": 5})
    except ValidationError as exc:
        err = exc.errors()[0]
        print("  模型级错误    ：", err["loc"], "|", err["msg"])


# ── 4. 序列化器与计算字段
class Money(BaseModel):
    cents: int = Field(description="最小单位：分")

    @computed_field
    @property
    def yuan(self) -> str:
        return f"{self.cents / 100:.2f}"

    @field_serializer("cents")
    def dump_cents(self, v: int) -> str:
        return f"{v}分"


def demo_serializer() -> None:
    print("=== 4. 序列化器与计算字段 ===")
    m = Money(cents=3900)
    print("  dump      ：", m.model_dump())
    print("  dump_json ：", m.model_dump_json())


# ── 5. 赋值校验与跳过校验
class Counter(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    steps: int


def demo_assign() -> None:
    print("=== 5. 赋值校验与跳过校验 ===")
    c = Counter(steps=0)
    c.steps = 1
    print("  正常赋值  ：", c.steps)
    try:
        c.steps = "一步"  # type: ignore[assignment]
    except ValidationError as exc:
        print("  赋值被拒  ：", exc.errors()[0]["type"])
    bypass = Counter.model_construct(steps="一步")
    print("  construct ：", bypass, "| 类型", type(bypass.steps).__name__)


# ── 6. 严格类型与 Json
class Payload(BaseModel):
    id: uuid.UUID
    qty: Annotated[int, Field(strict=True, gt=0)]
    meta: Json[dict]


def demo_types() -> None:
    print("=== 6. 严格类型与 Json ===")
    p = Payload.model_validate({
        "id": "12345678-1234-5678-1234-567812345678",
        "qty": 2,
        "meta": '{"a": 1}',
    })
    print("  uuid          ：", p.id)
    print("  Json 自动解析 ：", p.meta, type(p.meta).__name__)
    try:
        Payload.model_validate({"id": str(uuid.uuid4()), "qty": "2", "meta": {}})
    except ValidationError as exc:
        print("  strict 拒绝   ：", exc.errors()[0]["type"])


# ── 7. 动态模型与泛型
T = TypeVar("T")
Page = create_model("Page", items=(list[dict], ...), total=(int, 0))


class Box(BaseModel, Generic[T]):
    value: T


def demo_generic() -> None:
    print("=== 7. 动态模型与泛型 ===")
    print("  create_model ：", Page(items=[{"a": 1}]))
    print("  泛型实例     ：", Box[int](value=3))


# ── 8. 复制与裁剪
class Doc(BaseModel):
    title: str
    body: str = ""
    draft: bool = False


def demo_copy() -> None:
    print("=== 8. 复制与裁剪 ===")
    d = Doc(title="政策")
    print("  copy(update) ：", d.model_copy(update={"draft": True}))
    print("  exclude      ：", d.model_dump(exclude={"body"}))


# ── 9. 给厂商严格模式收拾 schema
class Verdict(BaseModel):
    reason: str = Field(description="理由")
    note: str | None = None


def demo_schema() -> None:
    print("=== 9. 严格模式的 schema ===")
    schema = Verdict.model_json_schema()
    print("  默认  ：", json.dumps(schema, ensure_ascii=False, sort_keys=True))
    strict_schema = {**schema, "required": list(schema["properties"]), "additionalProperties": False}
    print("  严格版：", json.dumps(strict_schema, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    for fn in (demo_alias, demo_root, demo_validators, demo_serializer, demo_assign,
               demo_types, demo_generic, demo_copy, demo_schema):
        fn()
