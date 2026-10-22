"""第 9 章产出：把"能断点续跑"的 Agent 做成可复用骨架。

核心不是"用了 checkpointer"，而是理解三件事：
  1. State 里放什么，决定了你能不能恢复
  2. thread_id 是什么，决定了会话怎么隔离
  3. 副作用（工具调用）的幂等，决定了恢复后会不会重复执行

本文件提供一个可直接跑的 LangGraph Agent，带：
  · SQLite 检查点（进程重启后可恢复）
  · 中断（interrupt）与恢复（Command(resume=...)）
  · 副作用幂等（用 executed 列表记录已执行的动作）
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from common.settings import ROOT

ROOT_DB = ROOT / ".traces" / "ch09_checkpoints.sqlite"


def _merge_list(left: list, right: list) -> list:
    """列表累加 reducer。

    为什么需要它？LangGraph 默认"覆盖"，多个步骤都往同一个列表写时，
    后写的会覆盖先写的——这是新手最常丢数据的地方。
    """
    return (left or []) + (right or [])


class TaskState(TypedDict, total=False):
    goal: str
    plan: list[str]
    cursor: int
    findings: Annotated[list[str], _merge_list]  # ← 累加，不覆盖
    executed: Annotated[list[str], _merge_list]  # ← 已执行的动作（幂等用）
    needs_confirm: bool
    final: str


# ---------------------------------------------------------------- 节点

def plan_node(state: TaskState) -> TaskState:
    goal = state.get("goal", "")
    return {
        "plan": [f"检索：{goal}", "整理要点", "撰写结论"],
        "cursor": 0,
    }


def execute_node(state: TaskState) -> TaskState:
    cursor = state.get("cursor", 0)
    plan = state.get("plan", [])
    if cursor >= len(plan):
        return {}

    step = plan[cursor]

    # 幂等检查：这一步做过就跳过（恢复场景下尤其重要）
    if step in state.get("executed", []):
        return {"cursor": cursor + 1, "findings": [f"[跳过] {step}（已执行）"]}

    # 遇到"撰写结论"前要人工确认
    if step.startswith("撰写") and not state.get("needs_confirm"):
        # interrupt 会把当前状态存进 checkpointer 并挂起整个运行
        answer = interrupt({"ask": f"即将执行：{step}，是否继续？", "step": step})
        return {"needs_confirm": bool(answer)}

    return {
        "cursor": cursor + 1,
        "findings": [f"[完成] {step}"],
        "executed": [step],
    }


def route(state: TaskState) -> Literal["execute", "finish"]:
    return "execute" if state.get("cursor", 0) < len(state.get("plan", [])) else "finish"


def finish_node(state: TaskState) -> TaskState:
    return {"final": "；".join(state.get("findings", []))}


def build(saver: SqliteSaver):
    g = StateGraph(TaskState)
    g.add_node("plan", plan_node)
    g.add_node("execute", execute_node)
    g.add_node("finish", finish_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "execute")
    g.add_conditional_edges("execute", route, {"execute": "execute", "finish": "finish"})
    g.add_edge("finish", END)
    return g.compile(checkpointer=saver)


def make_saver(db_path: Path | str) -> tuple[SqliteSaver, sqlite3.Connection]:
    """注意：check_same_thread=False 是必需的（FastAPI 多线程会用到）。

    返回值里带 connection，调用方负责关闭。
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn), conn
