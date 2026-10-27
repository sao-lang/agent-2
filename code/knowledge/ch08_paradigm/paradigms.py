"""三种编排范式跑同一个任务：固定工作流 / ReAct / Plan-and-Execute。

不联网。模型是脚本化的，工具是本地函数。要比较的只有两件事：步数与 token。
"""

from __future__ import annotations

import json
import time

# ---------------------------------------------------------------- 工具

def search_docs(q: str) -> list[str]:
    time.sleep(0.01)
    return [f"《退货政策》命中：{q}"]


def get_order(order_id: str) -> dict:
    time.sleep(0.01)
    return {"order_id": order_id, "signed_days_ago": 3}


def get_user(user_id: str) -> dict:
    time.sleep(0.01)
    return {"user_id": user_id, "level": "v2"}


def get_logistics(order_id: str) -> dict:
    time.sleep(0.01)
    return {"order_id": order_id, "shipped": True}


TOOLS = {
    "search_docs": search_docs,
    "get_order": get_order,
    "get_user": get_user,
    "get_logistics": get_logistics,
}


# ---------------------------------------------------------------- 计数

class Meter:
    """只数两件事：请求模型几次，以及这些请求总共带了多少字符。"""

    def __init__(self) -> None:
        self.steps = 0
        self.chars = 0

    def call(self, prompt_chars: int) -> None:
        self.steps += 1
        self.chars += prompt_chars

    @property
    def tokens(self) -> int:
        return self.chars // 2      # 粗估：2 字符约 1 token

    def __str__(self) -> str:
        return f"步数={self.steps}  token≈{self.tokens}"


# ---------------------------------------------------------------- 三种范式

def fixed_workflow(meter: Meter) -> dict:
    """固定工作流：顺序写死，不需要模型做任何选择。"""
    docs = search_docs("退货窗口")
    meter.call(200)
    order = get_order("A1001")
    meter.call(260)
    return {"docs": docs[0], "order": order}


BASE = "问题：A1001 能退吗？请一步步决定下一步调用哪个工具。"


def react(meter: Meter) -> dict:
    """ReAct：每一步都问模型下一步做什么，历史全量重发。"""
    history = BASE
    facts: dict = {}
    for _ in range(3):
        meter.call(len(history))          # 每次请求都带上全部历史
        if "docs" not in facts:
            facts["docs"] = search_docs("退货窗口")[0]
            history += f"\n观察：{facts['docs']}"
            continue
        if "order" not in facts:
            facts["order"] = get_order("A1001")
            history += f"\n观察：{json.dumps(facts['order'], ensure_ascii=False)}"
            continue
        break
    return facts


def plan_and_execute(meter: Meter) -> dict:
    """P&E：先出计划（1 步），再按计划执行（不再问模型），最后汇总（1 步）。"""
    meter.call(180)                        # 计划
    plan = ["search_docs", "get_order"]
    facts: dict = {}
    for name, arg in zip(plan, ["退货窗口", "A1001"]):
        facts[name] = TOOLS[name](arg)     # 执行阶段不消耗模型调用
    meter.call(320)                        # 汇总
    return facts


def main() -> None:
    for name, fn in [
        ("固定工作流", fixed_workflow),
        ("ReAct", react),
        ("Plan-and-Execute", plan_and_execute),
    ]:
        m = Meter()
        out = fn(m)
        print(f"{name:<18}{m}  产出字段={list(out.keys())}")


if __name__ == "__main__":
    main()
