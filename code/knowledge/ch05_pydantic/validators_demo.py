"""跨字段的一致性规则：类型都对，组合起来不对。

运行：python code/knowledge/ch05_pydantic/validators_demo.py
"""

from pydantic import BaseModel, ValidationError, model_validator


class Verdict(BaseModel):
    eligible: bool
    reason: str

    @model_validator(mode="after")
    def reason_matches_verdict(self):
        if self.eligible and "已拆封" in self.reason and "不影响" not in self.reason:
            raise ValueError("eligible=True 时，reason 不能只说已拆封")
        return self


CASES = [
    ("一致", {"eligible": True, "reason": "未拆封，符合七天无理由"}),
    ("矛盾", {"eligible": True, "reason": "已拆封"}),
    ("矛盾但写明了例外", {"eligible": True, "reason": "已拆封，但不影响二次销售"}),
]

for label, payload in CASES:
    try:
        print(f"{label:8}", Verdict.model_validate(payload))
    except ValidationError as exc:
        err = exc.errors()[0]
        print(f"{label:8}", "loc =", err["loc"], "|", err["msg"], "| input =", err["input"])
