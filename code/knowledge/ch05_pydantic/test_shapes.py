"""结构定义也要有测试：该收的收、该拒的拒。

运行：python code/knowledge/ch05_pydantic/test_shapes.py
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Verdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    eligible: bool
    reason: str = Field(min_length=1, max_length=40)


CASES = [
    ("合法", {"eligible": True, "reason": "未拆封"}, None),
    ("缺理由", {"eligible": True}, "reason"),
    ("空理由", {"eligible": False, "reason": ""}, "reason"),
    ("理由过长", {"eligible": True, "reason": "理由" * 30}, "reason"),
    ("类型漂移", {"eligible": "yes", "reason": "未拆封"}, "eligible"),
    ("多出字段", {"eligible": True, "reason": "未拆封", "score": 1}, "score"),
]

for label, payload, expect_field in CASES:
    try:
        Verdict.model_validate(payload)
        got = None
    except ValidationError as exc:
        got = exc.errors()[0]["loc"][0]
    status = "OK" if got == expect_field else "FAIL"
    print(f"{status}  {label:6} 期望拒于={expect_field} 实际={got}")
    assert got == expect_field, f"{label} 的判定变了"
