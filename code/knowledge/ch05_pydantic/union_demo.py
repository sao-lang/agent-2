"""一个字段有多种形状：用判别联合让校验器知道该按哪种解。

运行：python code/knowledge/ch05_pydantic/union_demo.py
"""

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class Refund(BaseModel):
    action: Literal["refund"]
    amount: float = Field(gt=0)


class AskHuman(BaseModel):
    action: Literal["ask_human"]
    question: str = Field(min_length=1)


class Stop(BaseModel):
    action: Literal["stop"]
    answer: str


Action = Annotated[Union[Refund, AskHuman, Stop], Field(discriminator="action")]


class Decision(BaseModel):
    step: int
    action: Action


print(json.dumps(Decision.model_json_schema()["properties"]["action"],
                 ensure_ascii=False, indent=2))

adapter = TypeAdapter(Action)
for raw in ['{"action": "refund", "amount": 39.0}',
            '{"action": "ask_human", "question": "哪一笔订单？"}',
            '{"action": "refund", "question": "哪一笔订单？"}']:
    try:
        print("通过：", adapter.validate_json(raw))
    except ValidationError as exc:
        err = exc.errors()[0]
        print("拒绝：", err["loc"], "|", err["msg"], "| input =", json.dumps(err["input"], ensure_ascii=False)[:60])
