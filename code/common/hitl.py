"""第 19 章产出：HITL（人机协作）的完整实现。

四个必须解决的问题：
  1. 什么动作需要人确认？（分级）
  2. 确认请求怎么发出去、怎么收回？（中断与恢复）
  3. 人不在怎么办？（超时与降级）
  4. 确认之后进程崩了怎么办？（幂等 + 检查点）

本文件基于 LangGraph 的 interrupt / Command(resume) 实现，可跑通完整链路。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from common.durable import _merge_list


class _StateBase(dict):
    """⚠️ 不要用裸 dict！

    这是我踩的坑：`StateGraph(dict)` 在 LangGraph 1.x 下不会把
    节点返回的增量合并进主状态，下游节点拿到的 state 是空的（KeyError: 'action'）。
    必须用 TypedDict（有明确的 schema）才能得到正常的增量合并语义。
    """


class HitlState(TypedDict, total=False):
    """图的 State schema。

    用 TypedDict 而不是裸 dict —— 裸 dict 在 LangGraph 1.x 下
    节点增量不会正确合并（见上面 _StateBase 的注释）。
    """
    goal: str
    action: str
    args: dict[str, Any]
    level: str
    card: dict[str, Any] | None
    approved: bool | None
    executed: Annotated[list[str], _merge_list]
    result: str
    log: Annotated[list[str], _merge_list]



# ============================================================ 审批分级
class ApprovalLevel(str, Enum):
    AUTO = "auto"            # 自动执行（只读、低风险）
    NOTIFY = "notify"        # 自动执行但要通知（可回滚）
    CONFIRM = "confirm"      # 必须人工确认
    FORBID = "forbid"        # 永远不允许


# 动作 → 级别的映射（**显式表，不能由模型决定**）
ACTION_LEVELS: dict[str, ApprovalLevel] = {
    "search": ApprovalLevel.AUTO,
    "get_order": ApprovalLevel.AUTO,
    "calc": ApprovalLevel.AUTO,
    "update_note": ApprovalLevel.NOTIFY,       # 加个备注：可回滚
    "send_email": ApprovalLevel.CONFIRM,       # 发邮件：不可撤销
    "refund": ApprovalLevel.CONFIRM,           # 退款：涉及钱
    "modify_order": ApprovalLevel.CONFIRM,
    "drop_table": ApprovalLevel.FORBID,
    "delete_user": ApprovalLevel.FORBID,
}

# 金额阈值：超过就升级要求（同一动作可能因参数不同而升级）
AMOUNT_THRESHOLD = 500.0
# 超时：人不在就不做（安全默认）
APPROVAL_TIMEOUT_SECONDS = 300


def decide_level(action: str, args: dict[str, Any]) -> ApprovalLevel:
    base = ACTION_LEVELS.get(action, ApprovalLevel.CONFIRM)  # 未登记 = 需要确认
    if base is ApprovalLevel.AUTO and action in ("refund",):
        return ApprovalLevel.CONFIRM
    amount = float(args.get("amount", 0) or 0)
    if amount >= AMOUNT_THRESHOLD and base is ApprovalLevel.CONFIRM:
        return ApprovalLevel.CONFIRM  # 已经是最高级，不再升级（示例留口子）
    return base


# ============================================================ 审批卡片

@dataclass
class ApprovalCard:
    """给人看的确认卡片。

    好卡片的三要素（缺一个，人就没法做判断）：
      1. 影响面（会改什么）
      2. 回滚预案（改错了怎么办）
      3. 有效期（过期自动失效，防止"三天后突然执行"）
    """

    request_id: str
    action: str
    args: dict[str, Any]
    impact: str
    rollback: str
    expires_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "args": self.args,
            "impact": self.impact,
            "rollback": self.rollback,
            "expires_in_sec": int(self.expires_at - time.time()),
        }


def make_card(action: str, args: dict[str, Any]) -> ApprovalCard:
    impacts = {
        "refund": f"将向用户退款 ¥{args.get('amount', 0)}，资金不可撤回",
        "send_email": f"将向 {args.get('to', '?')} 发送邮件，发送后不可撤回",
        "modify_order": f"将修改订单 {args.get('order', '?')} 的状态",
    }
    rollbacks = {
        "refund": "可通过财务冲正接口在 24 小时内撤销",
        "send_email": "无法撤回，需补发解释邮件",
        "modify_order": "保留修改前的快照，可一键还原",
    }
    return ApprovalCard(
        request_id=uuid.uuid4().hex[:12],
        action=action,
        args=args,
        impact=impacts.get(action, f"将执行 {action}"),
        rollback=rollbacks.get(action, "无自动回滚方案，请谨慎确认"),
        expires_at=time.time() + APPROVAL_TIMEOUT_SECONDS,
    )


def _card_payload(c: ApprovalCard) -> dict[str, Any]:
    """对外暴露的卡片：既给"还剩多久"，也给"绝对过期时刻"。"""
    d = c.to_dict()
    d["expires_at"] = c.expires_at
    return d


# ============================================================ 状态与图

@dataclass
class OrderState:
    goal: str
    action: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    level: str = ""
    card: dict[str, Any] | None = None
    approved: bool | None = None
    executed: list[str] = field(default_factory=list)   # 幂等键
    result: str = ""
    log: list[str] = field(default_factory=list)


def plan_node(state: dict) -> dict:
    """决定要做什么（真实系统里这是模型 + 工具选择）。

    ⚠️ 注意：LangGraph 节点返回的是**增量更新**，但 `print` 之类看到的
       state 可能是"上一次的完整状态"。这里显式设置所有相关字段，
       避免下游节点读到缺失的 key（我第一版就踩了 KeyError: 'action'）。
    """
    goal = state.get("goal", "")
    if "退款" in goal:
        action, args = "refund", {"order": "A12345", "amount": 299.0}
    elif "查" in goal:
        action, args = "get_order", {"order": "A12345"}
    else:
        action, args = "send_email", {"to": "user@example.com", "subject": "您好"}
    level = decide_level(action, args).value
    return {
        "goal": goal,
        "action": action,
        "args": args,
        "level": level,
        "approved": None,
        "result": "",
    }


def gate_node(state: dict) -> dict:
    """审批闸门：需要确认就中断，否则直接过。"""
    level = ApprovalLevel(state["level"])

    if level is ApprovalLevel.FORBID:
        return {"approved": False, "result": "禁止执行", "log": ["FORBID"]}

    if level is ApprovalLevel.AUTO:
        return {"approved": True, "log": ["AUTO-APPROVED"]}

    if level is ApprovalLevel.NOTIFY:
        # 不阻断，但记录（真实系统里这里发通知）
        return {"approved": True, "log": ["NOTIFIED"]}

    # CONFIRM：生成卡片并中断
    card = make_card(state["action"], state.get("args", {}))
    answer = interrupt(_card_payload(card))   # ← 整个图在这里挂起，状态落进 checkpointer

    # resume 回来的值：True / False / {"decision": "modify", "args": {...}}
    if isinstance(answer, dict):
        decision = answer.get("decision", "reject")
        new_args = answer.get("args")
        if decision in ("approve", "modify"):
            # 注意 "modify" 也是**批准**，只是参数被人工改过。
            # 我第一版只认 "approve"，导致"修改后批准"被当成拒绝（示例里金额没生效）。
            merged = {**state.get("args", {}), **(new_args or {})}
            return {
                "approved": True,
                "card": card.to_dict(),
                "args": merged,
                "log": ["CONFIRMED" if decision == "approve" else f"MODIFIED:{sorted((new_args or {}).keys())}"],
            }
        return {"approved": False, "card": card.to_dict(), "log": [f"REJECTED:{decision}"]}

    return {"approved": bool(answer), "card": card.to_dict(),
            "log": ["CONFIRMED" if answer else "REJECTED"]}


def execute_node(state: dict) -> dict:
    """执行动作（带幂等键）。"""
    if not state.get("approved"):
        return {"result": "未批准，未执行"}

    key = f"{state.get('action', '')}:{json.dumps(state.get('args', {}), sort_keys=True)}"
    if key in state.get("executed", []):
        return {"result": f"已执行过，跳过（幂等键 {key[:24]}）", "log": ["IDEMPOTENT-SKIP"]}

    action = state["action"]
    if action == "get_order":
        res = "订单 A12345：已签收"
    elif action == "refund":
        res = f"已退款 ¥{state['args'].get('amount', 0)}"
    else:
        res = f"已执行 {action}"

    return {"result": res, "executed": [key], "log": ["EXECUTED"]}


def build():
    g = StateGraph(HitlState)
    g.add_node("plan", plan_node)
    g.add_node("gate", gate_node)
    g.add_node("execute", execute_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "gate")
    g.add_edge("gate", "execute")
    g.add_edge("execute", END)
    return g.compile(checkpointer=InMemorySaver())


# ============================================================ 对外接口

@dataclass
class HitlService:
    """把"中断-审批-恢复"包成一个服务。

    三个方法对应三件事：
      start()   发起任务（可能立即返回 pending）
      pending() 拉取待审批列表（供前端展示）
      approve() 审批并恢复执行
    """

    app: Any = field(default_factory=build)
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _cfg(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def start(self, thread_id: str, goal: str) -> dict[str, Any]:
        out = self.app.invoke(
            {"goal": goal, "action": "", "args": {}, "level": "", "card": None,
             "approved": None, "executed": [], "result": "", "log": []},
            self._cfg(thread_id),
        )
        return self._handle(thread_id, out)

    def _handle(self, thread_id: str, out: dict) -> dict[str, Any]:
        if "__interrupt__" in out:
            card = out["__interrupt__"][0].value
            self.pending[thread_id] = card
            return {"status": "pending", "card": card, "thread_id": thread_id}
        self.pending.pop(thread_id, None)
        return {"status": "done", "result": out.get("result"), "log": out.get("log")}

    def list_pending(self) -> list[dict]:
        """列出待审批卡片，并正确标注是否已过期。

        ⚠️ 别写成 `now > expires_in_sec + now` —— 那个条件永远为 False，
           卡片会"永不过期"，于是三周后的一次点击仍然生效（本书实测踩过）。
           正确做法：卡片里存**绝对**过期时间（created_at + ttl），再和 now 比。
        """
        now = time.time()
        out: list[dict] = []
        for tid, c in self.pending.items():
            expires_at = c.get("expires_at") or (now + c.get("expires_in_sec", 0))
            out.append({**c, "thread_id": tid, "expired": now >= expires_at})
        return out

    def approve(self, thread_id: str, decision: str = "approve", new_args: dict | None = None) -> dict:
        """审批并恢复。过期卡片一律作废，不恢复执行。"""
        card = self.pending.get(thread_id)
        if card is not None:
            now = time.time()
            expires_at = card.get("expires_at") or (now + card.get("expires_in_sec", 0))
            if now >= expires_at:
                self.pending.pop(thread_id, None)
                return {"status": "expired", "thread_id": thread_id,
                        "result": "审批卡片已过期，本次作废（需重新发起）"}

        if decision == "approve":
            resume: Any = {"decision": "approve", "args": new_args} if new_args else True
        elif decision == "modify":
            resume = {"decision": "modify", "args": new_args or {}}
        else:
            resume = False

        out = self.app.invoke(Command(resume=resume), self._cfg(thread_id))
        return self._handle(thread_id, out)

    def state(self, thread_id: str) -> dict:
        snap = self.app.get_state(self._cfg(thread_id))
        return {"next": snap.next, "values": snap.values}
