"""dataclass 声明了类型，但不检查类型。

运行：python code/knowledge/ch05_pydantic/dataclass_vs_model.py
"""

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError


@dataclass
class VerdictDC:
    eligible: bool
    reason: str


class VerdictModel(BaseModel):
    eligible: bool
    reason: str


bad = {"eligible": "true", "reason": 123}

print("dataclass：", VerdictDC(**bad))
try:
    print("pydantic：", VerdictModel(**bad))
except ValidationError as exc:
    print("pydantic：", exc.errors()[0]["loc"], exc.errors()[0]["msg"])
