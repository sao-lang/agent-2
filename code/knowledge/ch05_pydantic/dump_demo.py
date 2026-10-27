"""校验之后的序列化：同一份数据，三种输出，用在哪一层。

运行：python code/knowledge/ch05_pydantic/dump_demo.py
"""

from pydantic import BaseModel, Field


class Item(BaseModel):
    sku: str
    qty: int = Field(ge=1, le=99)


class Order(BaseModel):
    order_id: str
    items: list[Item]
    note: str | None = None


order = Order(order_id="A1001", items=[Item(sku="S-1", qty=2)])

print("model_dump：", order.model_dump())
print("exclude_none：", order.model_dump(exclude_none=True))
print("model_dump_json：", order.model_dump_json())

raw = '''
{
  "order_id": "A1001",
  "items": [ {"sku": "S-1", "qty": 2} ],
  "note": null
}
'''
back = Order.model_validate_json(raw)
print("回读相等：", back == order)
print("原文与重新序列化不同：", raw != back.model_dump_json())
