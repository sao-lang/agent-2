"""字段说明会进 schema，模型也读得到。

运行：python code/knowledge/ch05_pydantic/descriptions_demo.py
"""

import json

from pydantic import BaseModel, Field


class Verdict(BaseModel):
    eligible: bool | None = Field(
        description="能否退货：符合条件为 true，明确不符合为 false，信息不足为 null"
    )
    reason: str = Field(
        description="不超过 40 字的理由，必须引用政策条款编号，如 P-7"
    )
    confidence: float = Field(
        ge=0, le=1, description="对本次判定的把握程度，0 到 1 之间的小数"
    )


schema = Verdict.model_json_schema()
print(json.dumps({name: {"type": prop.get("type", "anyOf"),
                         "description": prop.get("description")}
                  for name, prop in schema["properties"].items()},
                 ensure_ascii=False, indent=2))
print("必填字段：", schema["required"])
