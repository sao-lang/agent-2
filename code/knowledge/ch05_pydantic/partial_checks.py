"""手写校验与 pydantic 校验的对照。

运行：python code/knowledge/ch05_pydantic/partial_checks.py
"""

from pydantic import BaseModel, ValidationError


class Verdict(BaseModel):
    eligible: bool
    reason: str


def check_by_hand(payload: dict) -> str:
    """最常见的写法：把“字段在不在”当成校验。"""
    if "eligible" not in payload:
        return "缺 eligible"
    if "reason" not in payload:
        return "缺 reason"
    return "通过"


def check_with_pydantic(payload: dict) -> str:
    try:
        Verdict.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        return f"{first['loc'][0]}: {first['msg']} (input={first['input']!r})"
    return "通过"


CASES = [
    ("类型漂移", {"eligible": "true", "reason": "未拆封"}),
    ("缺字段", {"eligible": True}),
    ("多出字段", {"eligible": True, "reason": "未拆封", "confidence": 0.9}),
    ("全对", {"eligible": True, "reason": "未拆封"}),
]

for label, payload in CASES:
    print(f"{label:6} 手写={check_by_hand(payload):12} pydantic={check_with_pydantic(payload)}")
