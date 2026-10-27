"""嵌套结构出错时，错误定位到哪一层。

运行：python code/knowledge/ch05_pydantic/nested_errors.py
"""

from pydantic import BaseModel, Field, ValidationError


class Item(BaseModel):
    sku: str
    qty: int = Field(ge=1, le=99)


class Order(BaseModel):
    order_id: str
    items: list[Item]


PAYLOAD = {
    "order_id": "A1001",
    "items": [{"sku": "S-1", "qty": 2}, {"sku": "S-2", "qty": 0}],
}

try:
    Order.model_validate(PAYLOAD)
except ValidationError as exc:
    for err in exc.errors():
        print("loc =", err["loc"], "|", err["msg"], "| input =", err["input"])
