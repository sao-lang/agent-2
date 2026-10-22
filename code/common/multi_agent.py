"""第 25 章产出：多 Agent 的三条判据、三种形态、一个反例。

核心结论（本章要证明的）：
  · 多 Agent 是**成本放大器**，不是能力放大器
  · 只有在"能并行 / 需互看 / 装不下"三者至少满足一个时才该拆
  · 拆了之后必须做**单 Agent vs 多 Agent** 的三方对比（质量/成本/延迟）

本文件提供两种可跑的形态：
  1. Supervisor（协调者分派）—— LangGraph
  2. 并行子 Agent（fan-out/fan-in）—— LangGraph + Send
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


# ============================================================ 判据

@dataclass
class SplitCriteria:
    """拆分前必须回答的三个问题。

    任何一个答案是"否"，就不该拆。
    """

    can_parallel: bool            # 子任务能并行吗？
    need_cross_read: bool         # 子任务需要互相看结果吗？
    context_too_large: bool       # 单个上下文装不下吗？

    def verdict(self) -> tuple[bool, str]:
        if not any([self.can_parallel, self.need_cross_read, self.context_too_large]):
            return False, "不该拆：三个判据都不满足，拆了只会更贵更慢"
        if not self.can_parallel and not self.context_too_large:
            # 需要互相看结果，但装得下 → 用单 Agent + 反思（第 7 章）
            return False, "不该拆：需要交叉验证但上下文装得下，用单 Agent + Reflection"
        return True, "可以拆"


# ============================================================ 形态 1：Supervisor

def _merge(left: list, right: list) -> list:
    return (left or []) + (right or [])


class SupState(TypedDict, total=False):
    task: str
    next_agent: str
    findings: Annotated[list[str], _merge]
    rounds: int
    done: bool
    final: str


WORKERS = {
    "researcher": {"desc": "负责检索资料", "cost_per_call": 0.004},
    "analyst": {"desc": "负责数据分析", "cost_per_call": 0.006},
    "critic": {"desc": "负责挑错", "cost_per_call": 0.005},
}


def supervisor_node(state: SupState) -> dict:
    """协调者：只做分派与汇总，**不搬数据**。

    为什么"不搬数据"很重要？
    如果协调者要把 A 的输出转述给 B，它就会成为上下文瓶颈——
    所有信息都要过它一遍，token 消耗反而更高。
    """
    findings = state.get("findings", [])
    rounds = state.get("rounds", 0)

    if rounds >= 3:
        return {"done": True, "final": " | ".join(findings), "rounds": rounds}

    # 简单的分派策略（真实系统用模型决策，但要限制选择范围）
    order = ["researcher", "analyst", "critic"]
    idx = min(rounds, len(order) - 1)
    return {"next_agent": order[idx], "rounds": rounds + 1}


def worker_node(state: SupState) -> dict:
    agent = state.get("next_agent", "")
    time.sleep(0.15)                                   # 模拟工作
    finding = f"[{agent}] 产出第 {state.get('rounds', 0)} 项结果"
    return {"findings": [finding]}


def sup_route(state: SupState) -> str:
    return "end" if state.get("done") else "worker"


def build_supervisor():
    g = StateGraph(SupState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("worker", worker_node)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", sup_route, {"worker": "worker", "end": END})
    g.add_edge("worker", "supervisor")
    return g.compile()


# ============================================================ 形态 2：并行 fan-out

class FanState(TypedDict, total=False):
    task: str
    subtasks: list[str]
    sub: str                                   # 单个子任务（Send 时用）
    results: Annotated[list[str], _merge]      # ← 累加，否则并行分支互相覆盖
    final: str


def planner_node(state: FanState) -> dict:
    task = state.get("task", "")
    return {"subtasks": [f"{task} → 子任务{i}" for i in range(1, 4)]}


def fan_out(state: FanState) -> list:
    """动态 fan-out：返回 Send 列表，LangGraph 会并行执行。

    ⚠️ 关键：Send 的第二个参数是**该分支的输入 state**，
       它必须带上原来需要的字段（这里是 sub），否则 worker 读不到。
       我第一版只传了字符串，导致 worker 里 state.get("sub") 永远是空。
    """
    from langgraph.types import Send

    subtasks = state.get("subtasks", [])
    return [Send("worker", {"task": state.get("task", ""), "sub": s}) for s in subtasks]


def fan_worker_node(state: FanState) -> dict:
    time.sleep(0.3)                            # 模拟每个子任务 300ms
    sub = state.get("sub", "")
    return {"results": [f"done: {sub}"]}


def fan_join(state: FanState) -> dict:
    return {"final": f"汇总 {len(state.get('results', []))} 个子任务结果"}


def build_fan():
    g = StateGraph(FanState)
    g.add_node("planner", planner_node)
    g.add_node("worker", fan_worker_node)
    g.add_node("join", fan_join)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", fan_out, ["worker"])
    g.add_edge("worker", "join")
    g.add_edge("join", END)
    return g.compile()


# ============================================================ 成本对比

@dataclass
class CostModel:
    """对比"单 Agent"和"多 Agent"的成本。

    关键认知：多 Agent 的成本不是简单相加，而是相乘。
    因为协调者还要读所有子结果（上下文变长）。
    """

    base_cost_per_call: float = 0.005
    supervisor_overhead: float = 0.3     # 协调者额外消耗比例

    def single(self, steps: int = 3) -> dict:
        cost = steps * self.base_cost_per_call
        return {"agents": 1, "calls": steps, "cost": round(cost, 6), "latency_s": steps * 0.3}

    def multi(self, workers: int = 3, steps_per_worker: int = 2) -> dict:
        worker_calls = workers * steps_per_worker
        # 协调者：每轮都要读所有 findinds（上下文增长）
        sup_calls = workers + 1
        cost = worker_calls * self.base_cost_per_call + sup_calls * self.base_cost_per_call * (1 + self.supervisor_overhead)
        return {
            "agents": workers + 1,
            "calls": worker_calls + sup_calls,
            "cost": round(cost, 6),
            "latency_s": max(steps_per_worker * 0.3, steps_per_worker * 0.3),  # 并行时取 max
        }
