"""TypeAdapter：不是 BaseModel 的整体结构（列表、字典、联合）怎么校验。

一个模型校验单条，一批模型校验一个列表：后者不需要再包一个类。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class Verdict(BaseModel):
    eligible: bool
    reason: str = Field(min_length=1, max_length=40)


ADAPTER = TypeAdapter(list[Verdict])


def main() -> None:
    ok = ADAPTER.validate_python([{"eligible": True, "reason": "未拆封"}])
    print("整批：", ok)

    try:
        ADAPTER.validate_json('[{"eligible": true}, {"eligible": false, "reason": ""}]')
    except ValidationError as exc:
        for err in exc.errors():
            print("错误：", err["type"], err["loc"], "|", err["msg"])


if __name__ == "__main__":
    main()
