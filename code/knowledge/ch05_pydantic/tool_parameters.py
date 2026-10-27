"""同一份模型生成工具参数，再把模型给的参数校验回来。

运行：python code/knowledge/ch05_pydantic/tool_parameters.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import BaseModel, Field, ValidationError

from fake_server import chat_completion, client_for, scripted_server, tool_call


class OrderQuery(BaseModel):
    order_id: str = Field(pattern=r"^A\d{4}$", description="订单号，例如 A1001")
    detail: bool = Field(default=False, description="是否返回明细")


def tool_spec() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "查询订单状态。只查本账号订单。",
            "parameters": OrderQuery.model_json_schema(),
        },
    }


def respond(index, body):
    if index == 0:
        print("请求里的 tools[0].function.parameters：")
        print(json.dumps(body["tools"][0]["function"]["parameters"], ensure_ascii=False, indent=2))
        return chat_completion(tool_calls=[tool_call("get_order", {"order_id": "A1001"})],
                               finish_reason="tool_calls")
    return chat_completion("订单 A1001 已签收 3 天，可退。")


with scripted_server(respond) as base_url:
    client = client_for(base_url)
    messages = [{"role": "user", "content": "订单 A1001 能退吗？"}]
    first = client.chat.completions.create(
        model="demo-model", messages=messages, tools=[tool_spec()],
    )
    call = first.choices[0].message.tool_calls[0]
    print("模型给的 arguments：", call.function.arguments)

    try:
        query = OrderQuery.model_validate_json(call.function.arguments)
        print("校验通过：", query, "-> 执行结果", {"status": "已签收", "signed_days_ago": 3})
    except ValidationError as exc:
        print("参数不合法：", exc.errors()[0])
        raise SystemExit(1)

    messages += [
        first.choices[0].message.model_dump(exclude_none=True),
        {"role": "tool", "tool_call_id": call.id,
         "content": json.dumps({"status": "已签收", "signed_days_ago": 3}, ensure_ascii=False)},
    ]
    final = client.chat.completions.create(model="demo-model", messages=messages, tools=[tool_spec()])
    print("最终回答：", final.choices[0].message.content)
