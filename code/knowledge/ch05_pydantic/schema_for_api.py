"""一份模型定义，两种用法：本地校验 与 请求里的 json_schema。

运行：python code/knowledge/ch05_pydantic/schema_for_api.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import BaseModel, Field

from fake_server import chat_completion, client_for, scripted_server


class Item(BaseModel):
    sku: str
    qty: int = Field(ge=1, le=99)


class Order(BaseModel):
    order_id: str = Field(pattern=r"^A\d{4}$")
    items: list[Item]


print(json.dumps(Order.model_json_schema(), ensure_ascii=False, indent=2))


def respond(index, body):
    print("请求里的 response_format：",
          json.dumps(body.get("response_format"), ensure_ascii=False)[:160])
    return chat_completion('{"order_id": "A1001", "items": [{"sku": "S-1", "qty": 2}]}',
                           usage=(60, 20))


with scripted_server(respond) as base_url:
    client = client_for(base_url)
    reply = client.chat.completions.create(
        model="demo-model",
        messages=[{"role": "user", "content": "把订单 A1001 转成 JSON。"}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "Order",
                "strict": True,
                "schema": Order.model_json_schema(),
            },
        },
    )
    order = Order.model_validate_json(reply.choices[0].message.content)
    print("校验通过：", order)
