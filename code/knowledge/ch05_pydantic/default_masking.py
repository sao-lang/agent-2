"""默认值会掩盖缺字段：同一条错误数据，三种模型配置三种结论。

运行：python code/knowledge/ch05_pydantic/default_masking.py
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PAYLOAD = {"eligible": True}


class WithDefault(BaseModel):
    eligible: bool
    reason: str = ""


class WithForbid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    reason: str


class WithAlias(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eligible: bool
    why: str = Field(default="", alias="reason")


print("默认值兜底：", WithDefault.model_validate(PAYLOAD))
try:
    WithForbid.model_validate(PAYLOAD)
except ValidationError as exc:
    print("必填：", exc.errors()[0]["msg"])

try:
    WithForbid.model_validate({**PAYLOAD, "reason": "未拆封", "confidence": 0.9})
except ValidationError as exc:
    print("额外字段：", exc.errors()[0]["msg"])

print("字段改名后仍能用旧名：", WithAlias.model_validate({"eligible": True, "reason": "未拆封"}))
