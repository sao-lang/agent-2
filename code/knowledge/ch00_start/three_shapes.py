"""三个程序，演示一次调用 → 固定流程 → 循环 的差别。

不联网。模型部分用一个确定性的假后端代替，行为在 `FakeModel` 里写清楚。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 假后端

ORDERS = {"A1001": {"status": "已发货", "eta": "2 天"}}
POLICIES = {"退货": "签收后 7 天内可退，商品需未拆封。"}


@dataclass
class FakeModel:
    """一个确定性的"模型"。它只做两件事：决定下一步动作，或给出最终回答。"""

    # 第几次被调用时给出最终回答。None 表示永远不给，用来演示停不下来。
    answer_at: int | None = 2
    calls: int = 0
    seen: list[str] = field(default_factory=list)

    def __call__(self, messages: list[dict]) -> dict:
        self.calls += 1
        self.seen.append(messages[-1]["content"])

        if self.answer_at is not None and self.calls >= self.answer_at:
            return {"type": "answer", "content": "订单 A1001 已发货，预计 2 天到。退货政策：签收后 7 天内可退。"}

        # 模型不会自己查数据，它只会"说要查什么"
        if "A1001" in messages[0]["content"]:
            return {"type": "tool_call", "name": "get_order", "args": {"order_id": "A1001"}}
        return {"type": "tool_call", "name": "get_policy", "args": {"topic": "退货"}}


def execute(name: str, args: dict) -> str:
    if name == "get_order":
        return json.dumps(ORDERS.get(args["order_id"], {"error": "not found"}), ensure_ascii=False)
    if name == "get_policy":
        return POLICIES.get(args["topic"], "未找到")
    raise KeyError(name)


# ---------------------------------------------------------------- 示例一：单次调用

def one_shot(question: str) -> str:
    """一次调用。模型只能凭训练时见过的内容回答。"""
    model = FakeModel(answer_at=1)
    return model([{"role": "user", "content": question}])["content"]


# ---------------------------------------------------------------- 示例二：固定流程

def fixed_pipeline(order_id: str) -> str:
    """固定流程（workflow）。步骤在设计期写死，运行时没有分支。"""
    order = execute("get_order", {"order_id": order_id})
    policy = execute("get_policy", {"topic": "退货"})
    return f"订单：{order}；政策：{policy}"


# ---------------------------------------------------------------- 示例三：循环

def agent_loop(question: str, max_steps: int = 5) -> tuple[str, int, str]:
    """循环（agent）。由模型决定下一步，代码只负责执行和回灌。

    返回 (最终回答, 实际步数, 终止原因)。
    """
    model = FakeModel(answer_at=2)
    messages: list[dict] = [{"role": "user", "content": question}]

    for step in range(1, max_steps + 1):
        reply = model(messages)

        if reply["type"] == "answer":
            return reply["content"], step, "answered"

        # 关键：模型没有执行能力，是这段代码替它执行，再把结果送回对话
        result = execute(reply["name"], reply["args"])
        messages.append({"role": "assistant", "content": f"调用 {reply['name']}({reply['args']})"})
        messages.append({"role": "tool", "content": result})

    return "（未能在步数上限内给出回答）", max_steps, "max_steps"


def never_stops(max_steps: int = 5) -> tuple[int, str]:
    """答案永不到来时的样子。这就是"跑飞"的最简形态。"""
    model = FakeModel(answer_at=None)
    messages: list[dict] = [{"role": "user", "content": "订单 A1001 什么时候到？"}]
    for step in range(1, max_steps + 1):
        reply = model(messages)
        messages.append({"role": "tool", "content": execute(reply["name"], reply["args"])})
    return model.calls, "max_steps"


# ---------------------------------------------------------------- 演示

if __name__ == "__main__":
    q = "订单 A1001 什么时候到？能退吗？"

    print("=== 单次调用 ===")
    print(one_shot(q))

    print("\n=== 固定流程 ===")
    print(fixed_pipeline("A1001"))

    print("\n=== 循环 ===")
    answer, steps, reason = agent_loop(q)
    print(f"步数={steps} 终止原因={reason}")
    print(answer)

    print("\n=== 循环但模型永不收敛 ===")
    calls, reason = never_stops()
    print(f"模型被调用 {calls} 次，终止原因={reason}")
