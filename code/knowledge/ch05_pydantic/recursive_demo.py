"""递归结构：计划树用同一个模型套自己。

运行：python code/knowledge/ch05_pydantic/recursive_demo.py
"""

import json

from pydantic import BaseModel


class PlanStep(BaseModel):
    name: str
    children: list["PlanStep"] = []


plan = PlanStep.model_validate({
    "name": "处理退货",
    "children": [
        {"name": "查订单", "children": [{"name": "调 get_order"}]},
        {"name": "查政策"},
    ],
})
print(plan)

schema = PlanStep.model_json_schema()
print(json.dumps(schema, ensure_ascii=False, indent=2))
print("递归深度 2 也能校验：", PlanStep.model_validate(
    {"name": "a", "children": [{"name": "b", "children": [{"name": "c"}]}]}
).children[0].children[0].name)
