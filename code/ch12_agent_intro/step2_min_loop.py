"""第 12 章 step2：30 行写一个最小 Agent 循环（离线）。

运行：
    python code/ch12_agent_intro/step2_min_loop.py

上一级的痛点（step1）：你知道要五个零件了，但不知道怎么把它们装起来。

这一级做什么：写一个**完整但最小**的 Agent 循环，然后跑三个任务，
             让你看清每一步在做什么、三个终止条件分别在哪一行。

核心：这个循环不会有任何变化 —— LangGraph / AutoGen / CrewAI 的内核都是它。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


# ============================================================ 工具
def query_order(order_id: str) -> str:
    db = {"A12345": "已签收3天", "B777": "已签收20天"}
    return db.get(order_id, "订单不存在")


def check_policy(status: str) -> str:
    if "3天" in status:
        return "7天内可无理由退货"
    if "20天" in status:
        return "已超7天，仅在质量问题时可退"
    return "未知"


def submit_refund(order_id: str) -> str:
    return f"R-{order_id[-3:]}"


TOOLS: dict[str, Callable[..., str]] = {
    "query_order": query_order,
    "check_policy": check_policy,
    "submit_refund": submit_refund,
}

SCHEMAS = {
    "query_order": {"order_id": "str，订单号"},
    "check_policy": {"status": "str，订单状态"},
    "submit_refund": {"order_id": "str，订单号"},
}


# ============================================================ 假模型
@dataclass
class Action:
    type: str  # "tool" | "answer"
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def signature(self) -> str:
        return f"{self.name}:{json.dumps(self.args, sort_keys=True, ensure_ascii=False)}"


class FakeLLM:
    """按 state 决定下一步。真实模型是生成 tool_calls，这里是规则模拟。"""

    def decide(self, state: dict, task: str) -> Action:
        oid = state.get("input_order", "A12345")

        if state.get("order_status") is None:
            return Action("tool", "query_order", {"order_id": oid})
        if state.get("policy") is None:
            return Action("tool", "check_policy", {"status": state["order_status"]})
        if state.get("refund_no") is None and "可无理由退货" in state["policy"]:
            return Action("tool", "submit_refund", {"order_id": oid})

        return Action("answer", text=(
            f"订单 {oid}：{state['order_status']}；政策：{state['policy']}；"
            f"结果：{state.get('refund_no') or '不满足无理由退货条件，未发起退款'}"
        ))


# ============================================================ 最小循环
def run_agent(task: str, order_id: str, max_steps: int = 6, verbose: bool = True) -> dict:
    llm = FakeLLM()
    state: dict[str, Any] = {
        "input_order": order_id,
        "order_status": None,
        "policy": None,
        "refund_no": None,
        "steps": 0,
        "seen": set(),
    }

    while True:
        state["steps"] += 1
        action = llm.decide(state, task)          # ① 模型决策
        if verbose:
            print(f"  step{state['steps']}: {action.type} "
                  f"{action.name}({action.args})" if action.type == "tool"
                  else f"  step{state['steps']}: answer -> {action.text}")

        # 终止条件 ①：模型说完了
        if action.type == "answer":
            return {"stop": "answer", "steps": state["steps"], "state": state, "text": action.text}

        # 执行工具
        fn = TOOLS.get(action.name)
        if fn is None:
            return {"stop": "unknown_tool", "steps": state["steps"], "state": state,
                    "text": f"工具 {action.name} 不存在"}
        result = fn(**action.args)

        # 终止条件 ③：空转检测（同签名第二次 → 立即停）
        sig = action.signature()
        if sig in state["seen"]:
            return {"stop": "no_progress", "steps": state["steps"], "state": state,
                    "text": f"重复动作 {sig}，判定空转"}
        state["seen"].add(sig)

        # 写回状态（零件③）
        if action.name == "query_order":
            state["order_status"] = result
        elif action.name == "check_policy":
            state["policy"] = result
        elif action.name == "submit_refund":
            state["refund_no"] = result

        # 终止条件 ②：步数上限
        if state["steps"] >= max_steps:
            return {"stop": "max_steps", "steps": state["steps"], "state": state,
                    "text": f"超过 {max_steps} 步"}


def main() -> None:
    print("=" * 88)
    print("最小 Agent 循环：15 行核心 + 三个终止条件")
    print("=" * 88)

    print("\n工具清单（模型看到的就是这三行）：")
    for name, schema in SCHEMAS.items():
        print(f"  {name}({', '.join(f'{k}: {v}' for k, v in schema.items())})")

    for label, oid in (("可退订单", "A12345"), ("超期订单", "B777")):
        print(f"\n{'=' * 88}")
        print(f"任务：{label}（{oid}）")
        print("=" * 88)
        r = run_agent("帮我退了这个订单", oid)
        print(f"\n  停止原因：{r['stop']}　步数：{r['steps']}")
        print(f"  最终答案：{r['text']}")

    print("\n" + "=" * 88)
    print("循环的骨架（去掉业务逻辑就这几行）")
    print("=" * 88)
    print("""  while True:
      state.steps += 1
      action = llm.decide(state)              # ← 模型决定下一步

      if action.type == "answer":             # ← 终止条件 ①
          return action.text

      result = TOOLS[action.name](**action.args)   # ← 执行
      state.observe(action, result)                # ← 写回状态

      if action.signature in state.seen:      # ← 终止条件 ③（空转）
          return "no progress"

      if state.steps >= MAX_STEPS:            # ← 终止条件 ②（上限）
          return "max steps\"""")

    print("\n" + "=" * 88)
    print("三个终止条件，各挡一种失控")
    print("=" * 88)
    rows = [
        ("① 模型说完了", "正常结束", "永远不会结束"),
        ("② 步数上限", "死循环", "跑到超时/爆预算"),
        ("③ 空转检测", "重复同一动作", "**步数没超，但钱在烧**"),
    ]
    print(f"  {'条件':<16}{'挡什么':<20}不加会怎样")
    print("  " + "-" * 74)
    for a, b, c in rows:
        print(f"  {a:<16}{b:<20}{c}")

    print("\n" + "=" * 88)
    print("为什么只有 ② 不够")
    print("=" * 88)
    print("  真实项目最常见的失控不是'跑 1000 步'，而是：")
    print("    在 20 步里，把同一个工具重复调了 15 次。")
    print()
    print("  步数上限要等到第 20 步才生效 —— 那 15 次已经白花钱了。")
    print("  空转检测能在第 2 次就拦住。")
    print("  第 17 章会给出实测：加空转检测，成本从 ¥0.0139 降到 ¥0.0016（−88%）。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  · 这个 while 循环就是所有 Agent 框架的内核，**不会再变**。")
    print("  · 框架加的是：持久化、并行、人工介入、可观测 —— 循环本身不动。")
    print("  · **三个终止条件必须都在**，少一个就是线上事故的种子。")
    print("  · 状态要显式写回：`state.observe()` 这一步最容易漏，漏了就退化成 step1 的'少状态'。")
    print()
    print("  下一级（step3）：不是所有任务都该用这个循环 —— 有时候 Workflow 更好。")

    r = run_agent("帮我退了这个订单", "A12345", verbose=False)
    assert r["stop"] == "answer" and r["steps"] == 3


if __name__ == "__main__":
    main()
