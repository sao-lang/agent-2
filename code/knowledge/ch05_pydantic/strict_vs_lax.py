"""宽松模式与严格模式：同一份脏数据，两种结论。

运行：python code/knowledge/ch05_pydantic/strict_vs_lax.py
"""

from pydantic import BaseModel, ConfigDict, ValidationError


class LaxVerdict(BaseModel):
    eligible: bool
    confidence: float


class StrictVerdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    eligible: bool
    confidence: float


DIRTY = {"eligible": "true", "confidence": "0.83", "note": "模型顺手多写了一个字段"}

print("宽松：", LaxVerdict.model_validate(DIRTY))
try:
    StrictVerdict.model_validate(DIRTY)
except ValidationError as exc:
    for err in exc.errors():
        print("严格：", err["loc"], err["msg"], "input=", repr(err["input"]))

print("严格模式只喂合法的值：", StrictVerdict(eligible=True, confidence=0.83))
