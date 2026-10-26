"""第 12 章 step1：Agent 的五类零件——少一个就转不起来（离线）。

运行：
    python code/ch12_agent_intro/step1_five_parts.py

上一级的痛点（第 11 章）：RAG 能答问题了，但它只会"答"。用户说"帮我退了这单"，
                     RAG 会告诉你退货流程，然后……就没有然后了。

这一级做什么：把 Agent 拆成五类零件，然后**逐个拿掉**，看它怎么坏。
  · 少 LLM      → 没人做决策
  · 少 工具     → 只会说不会做
  · 少 状态     → 每轮都失忆
  · 少 循环     → 只能走一步
  · 少 终止条件 → 死循环烧钱

关键：**这一章不讲 ReAct、不讲框架**，只讲"一个能自己做事的东西，最少需要什么"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ============================================================ 零件一：模型（离线模拟）
class FakeLLM:
    """按当前上下文决定"下一步做什么"。

    真实模型是靠概率生成 tool_calls；这里用规则模拟，
    目的是让**决策过程可见**，而不是让回答像人。
    """

    def decide(self, state: "State", tools: list[str], has_loop: bool) -> dict:
        # ① 没有工具 → 只能凭记忆答（这就是裸 LLM）
        if not tools:
            return {"type": "answer", "text": "退货需要 7 天内申请。（我没法查你的订单，也退不了）"}

        # ② 没有状态 → 每轮都失忆，永远在查第一步
        if state.facts is None:
            return {"type": "tool", "name": "query_order", "args": {"order_id": state.input_order}}

        order = state.facts.get("order_id")

        # ③ 正常流程：订单 → 政策 → 判定
        if order is None:
            return {"type": "tool", "name": "query_order", "args": {"order_id": state.input_order}}

        if "order_status" not in state.facts:
            return {"type": "tool", "name": "query_order", "args": {"order_id": order}}

        if "policy" not in state.facts:
            return {"type": "tool", "name": "check_policy", "args": {"status": state.facts["order_status"]}}

        return {
            "type": "answer",
            "text": f"订单 {order} 状态为{state.facts['order_status']}，"
                    f"按政策{state.facts['policy']}，可以为您发起退货。",
        }


# ============================================================ 零件二：工具
def query_order(order_id: str | None) -> str:
    if not order_id:
        return "错误：没有订单号"
    return "已签收3天"


def check_policy(status: str) -> str:
    return "7天内可无理由退货" if "3天" in status else "超过7天需质检"


TOOLS = {"query_order": query_order, "check_policy": check_policy}


# ============================================================ 零件三/四/五：状态 + 循环 + 终止
class Stop(str, Enum):
    ANSWER = "answer"          # 答完了（是否真做到，看有没有工具）
    DEFLECTED = "deflected"    # 只会说不会做
    MAX_STEPS = "max_steps"
    NO_PROGRESS = "no_progress"


@dataclass
class State:
    input_order: str = "A12345"
    facts: dict = field(default_factory=dict)
    steps: int = 0


@dataclass
class Config:
    has_llm: bool = True
    has_tools: bool = True
    has_state: bool = True
    has_loop: bool = True
    max_steps: int = 6
    detect_no_progress: bool = True


def run(cfg: Config) -> dict:
    llm = FakeLLM()
    state = State()
    if not cfg.has_state:
        # 状态是 None：每轮都从零开始
        state.facts = None  # type: ignore[assignment]

    tools = list(TOOLS) if cfg.has_tools else []
    trace: list[str] = []
    seen: set[str] = set()
    stop = Stop.MAX_STEPS

    if not cfg.has_loop:
        # 没有循环：只能执行一次决策，然后停
        d = llm.decide(state, tools, False)
        trace.append(f"step1: {d}")
        return {"stop": Stop.NO_PROGRESS, "steps": 1, "trace": trace,
                "note": "只走了一步就停了，任务没完成"}

    # 没有终止条件 = 不设步数上限、也不做空转检测
    limit = cfg.max_steps if cfg.detect_no_progress else 999

    # 模拟"模型陷入重复动作"：真实场景里它会把同一个工具调十几次
    if not cfg.detect_no_progress:
        for step in range(1, limit + 1):
            state.steps = step
            trace.append(f"step{step}: 再次调用 query_order（它忘了已经查过）")
            if step >= 8:  # 跑到 8 步仍在转 —— 停不下来
                break
        return {"stop": Stop.MAX_STEPS, "steps": min(step, limit), "trace": trace}

    for step in range(1, limit + 1):
        state.steps = step

        if not cfg.has_llm:
            trace.append(f"step{step}: 没有模型，无法决策 → 卡死")
            stop = Stop.NO_PROGRESS
            break

        d = llm.decide(state, tools, cfg.has_loop)
        trace.append(f"step{step}: {d}")

        if d["type"] == "answer":
            # 没有工具时"答完"只是嘴上说说，任务并没真做到
            stop = Stop.ANSWER if tools else Stop.DEFLECTED
            break

        # 执行工具
        name = d["name"]
        if name not in TOOLS:
            trace.append(f"step{step}: 工具 {name} 不存在")
            stop = Stop.NO_PROGRESS
            break
        result = TOOLS[name](**d["args"])

        # 无进展检测：同样的 (工具, 参数) 第二次出现就是空转
        key = f"{name}:{d['args']}"
        if cfg.detect_no_progress and key in seen:
            trace.append(f"step{step}: 重复调用 {key}，判定为空转")
            stop = Stop.NO_PROGRESS
            break
        seen.add(key)

        if cfg.has_state and state.facts is not None:
            state.facts[name.replace("query_order", "order_status").replace("check_policy", "policy")] = result
            if name == "query_order":
                state.facts["order_id"] = d["args"]["order_id"]

    return {"stop": stop, "steps": state.steps, "trace": trace}


def main() -> None:
    print("=" * 90)
    print("一个 Agent 最少要什么：逐个拿掉零件")
    print("=" * 90)

    cases = [
        ("完整（五件都有）", Config()),
        ("少了 工具", Config(has_tools=False)),
        ("少了 状态", Config(has_state=False)),
        ("少了 循环", Config(has_loop=False)),
        ("少了 模型", Config(has_llm=False)),
        ("少了 终止条件", Config(max_steps=12, detect_no_progress=False)),
    ]

    print(f"{'配置':<18}{'停止原因':<12}{'步数':>5}   结果")
    print("-" * 90)
    results = {}
    for label, cfg in cases:
        r = run(cfg)
        results[label] = r
        verdict = {
            Stop.ANSWER: "✅ 完成任务",
            Stop.DEFLECTED: "❌ 只会说不会做（任务没真做到）",
            Stop.MAX_STEPS: "❌ 跑到上限才停（可能白烧钱）",
            Stop.NO_PROGRESS: "❌ 卡住/空转",
        }[r["stop"]]
        print(f"{label:<18}{r['stop'].value:<12}{r['steps']:>5}   {verdict}")
    print("-" * 90)

    print("\n" + "=" * 90)
    print("逐条看：少了零件之后到底发生了什么")
    print("=" * 90)
    for label in ("少了 工具", "少了 状态", "少了 循环", "少了 终止条件"):
        print(f"\n【{label}】")
        for line in results[label]["trace"][:6]:
            print(f"  {line}")
        if len(results[label]["trace"]) > 6:
            print(f"  ……（共 {len(results[label]['trace'])} 步）")

    print("\n" + "=" * 90)
    print("五类零件各自的职责（这就是 Agent 的定义）")
    print("=" * 90)
    parts = [
        ("① 模型 LLM", "做决策：下一步该干什么", "只能聊天，不能做事"),
        ("② 工具 Tool", "真正执行动作：查库、调 API、写文件", "只会说'你可以去退款'，不会真退"),
        ("③ 状态 State", "记住已经知道了什么", "反复查同一件事，永远问'你的订单号是多少'"),
        ("④ 循环 Loop", "能连做多步", "一次只能做一件事"),
        ("⑤ 终止条件", "知道什么时候停", "**无限循环，一夜烧掉几百块**（第 17 章）"),
    ]
    print(f"  {'零件':<14}{'职责':<32}少了会怎样")
    print("  " + "-" * 82)
    for a, b, c in parts:
        print(f"  {a:<14}{b:<32}{c}")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · **Agent = 模型 + 工具 + 状态 + 循环 + 终止条件。** 五件缺一不可。")
    print("  · 和 RAG 的区别：RAG 是'给模型补上下文'，Agent 是'让模型真的动手'。")
    print("  · 和 Workflow 的区别：Workflow 的路线是人写死的，Agent 的路线是模型临场决定的。")
    print("  · **最危险的零件是'终止条件'** —— 前四个缺了你会立刻发现，")
    print("    这个缺了会跑得很欢，直到账单来了（第 17 章专讲）。")
    print()
    print("  下一级（step2）：把五件装配起来，写一个 30 行的最小 Agent。")

    assert results["完整（五件都有）"]["stop"] is Stop.ANSWER
    assert results["少了 循环"]["steps"] == 1


if __name__ == "__main__":
    main()
