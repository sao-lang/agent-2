"""字段类型的选择：金额、时间、枚举、ID。

运行：python code/knowledge/ch05_pydantic/types_demo.py
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Refund(BaseModel):
    order_id: str = Field(pattern=r"^A\d{4}$", description="订单号，A 加四位数字")
    amount: Decimal = Field(gt=0, decimal_places=2, description="退款金额，保留两位小数")
    created_at: datetime = Field(description="申请时间，ISO 8601")
    channel: Literal["app", "web", "phone"] = Field(description="提交渠道")


good = {"order_id": "A1001", "amount": "39.00",
        "created_at": "2026-10-28T10:00:00", "channel": "app"}

refund = Refund.model_validate(good)
print(refund)
print("金额字段的 schema：", Refund.model_json_schema()["properties"]["amount"])
print("枚举字段的 schema：", Refund.model_json_schema()["properties"]["channel"])

try:
    Refund.model_validate({**good, "amount": "39.005"})
except ValidationError as exc:
    print("三位小数被拒：", exc.errors()[0]["msg"])

try:
    Refund.model_validate({**good, "channel": "email"})
except ValidationError as exc:
    print("不在枚举里：", exc.errors()[0]["msg"])

print("float 相加：", 0.1 + 0.2)
print("Decimal 相加：", Decimal("0.1") + Decimal("0.2"))

