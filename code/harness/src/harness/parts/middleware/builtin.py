"""四个内置层（SPEC M13.4）：Context / Checkpoint / BudgetGuard / Trace /
Approval / Idempotency / Validate / TaskBoard。

只实现与 step / model_call / tool_call 链直接相关的层；护栏、子 agent 等在后续迭代。
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable

from harness.contracts.approval_errors import ApprovalRequired
from harness.contracts.events import RunEvent
from harness.contracts.types import (
    ApprovalRequest,
    Budget,
    ModelRequest,
    ModelResponse,
    StepRequest,
    StepResponse,
    ToolRequest,
    ToolResponse,
    Verdict,
)
from harness.parts.framing import ChatEncoder, ModelFramer
from harness.parts.middleware.base import Layer, layer


# ------------------------------------------------------------------ Context


def context_layer(*, system: str = "", encoder: Any = None) -> Layer:
    """插点 model_call：取景 → 编码，替换请求里的消息（SPEC M6）。"""
    framer = ModelFramer(system=system)
    enc = encoder or ChatEncoder()

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ModelRequest) or req.state is None:
                return await nxt(req)
            frame = await framer.frame(req.state, budget=req.budget or Budget())
            pack = await enc.encode(frame)
            return await nxt(replace(req, messages=tuple(pack.messages), frame=frame))

        return handler

    return layer("context", ["model_call"], build, before=["input_guard"])


# ------------------------------------------------------------------ Checkpoint


def state_namespace(state: Any) -> Any:
    from harness.contracts.types import Namespace

    return Namespace(
        tenant=state.session.tenant or "default",
        user=state.goal.user_id or "anonymous",
        session=state.session.session_id,
    )


def checkpoint_layer(*, store: Any, cap: str = "store") -> Layer:
    """插点 step：每步落盘，rev 递增（不变量 1）。"""

    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            state = getattr(req, "state", None)
            if state is not None and isinstance(response, StepResponse):
                await store.put(
                    getattr(req, "ns", None) or state_namespace(state),
                    state.session.session_id,
                    state,
                    expect_rev=state.rev,
                )
            return response

        return handler

    return layer("checkpoint", ["step"], build, needs=[cap], after=["validate"])


# ------------------------------------------------------------------ Budget


def budget_layer(*, budget: Budget) -> Layer:
    """插点 run + model_call：记账；超限抛 BudgetError（SPEC M8.2）。"""

    def build(nxt):
        async def handler(req):
            from harness.contracts.errors import BudgetExceeded

            if budget.exhausted:
                raise BudgetExceeded(f"预算耗尽：{budget.snapshot()}")
            response = await nxt(req)
            if isinstance(response, ModelResponse):
                used = int(response.usage.get("total", 0))
                budget.spend(tokens=used, calls=1)
            return response

        return handler

    return layer("budget", ["run", "model_call"], build, after=["tenancy"])


# ------------------------------------------------------------------ Trace


def trace_layer(*, sink: Any, clock: Any = None) -> Layer:
    """全部插点：开/闭 span 并发事件（SPEC M10.1）。异常不得影响请求。"""

    def build(nxt):
        async def handler(req):
            name = type(req).__name__
            start = int((clock.now().timestamp() if clock else time.time()) * 1000)
            try:
                response = await nxt(req)
            finally:
                end = int((clock.now().timestamp() if clock else time.time()) * 1000)
                try:
                    await sink.emit(
                        RunEvent(
                            name="span.end",
                            ts_ms=end,
                            fields={"request": name, "start_ms": start, "end_ms": end},
                        )
                    )
                except Exception:  # noqa: BLE001 - 观测不得影响请求
                    pass
            return response

        return handler

    return layer("trace", ["run", "step", "model_call", "tool_call"], build,
                 needs=["events"], before=["audit"])


# ------------------------------------------------------------------ Approval


def approval_layer(
    *,
    channel: Any = None,
    when: tuple[str, ...] = ("write", "shell"),
    always: tuple[str, ...] = (),
    timeout_s: float = 0.0,
) -> Layer:
    """插点 tool_call：按 `side_effects` 判定是否需要人点头（SPEC M8.3）。

    判定为"需要"且拿不到既有决定时抛 `ApprovalRequired`；由 `Classify` 映射成
    `NEEDS_APPROVAL`，运行层据此落盘挂起。**不猜工具名**，只看元数据。
    """

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ToolRequest):
                return await nxt(req)
            spec = req.spec
            side = str(getattr(spec, "side_effects", "pure"))
            name = getattr(spec, "name", "")
            needed = bool(getattr(spec, "needs_approval", False)) or side in when or name in always
            if not needed:
                return await nxt(req)

            card = {
                "title": f"需要批准：{name}",
                "tool": name,
                "side_effects": side,
                "args": dict(req.step.args),
            }
            if channel is not None:
                approval_id = await channel.request(
                    ApprovalRequest(id="", step=req.step, reason=f"side_effects={side}", card=card)
                )
                decision = await channel.wait(approval_id, timeout_s=timeout_s)
                if decision is not None:
                    if decision.action == "reject":
                        from harness.contracts.errors import PolicyError

                        raise PolicyError(f"人工驳回：{decision.reason or name}")
                    step = req.step
                    if decision.action == "modify":
                        step = replace(step, args={**step.args, **decision.args})
                    return await nxt(replace(req, step=step))
            raise ApprovalRequired(req.step.id, reason=f"side_effects={side}", card=card, tool=name)

        return handler

    return layer("approval", ["tool_call"], build, after=["idempotency"])


# ------------------------------------------------------------------ Idempotency


def default_idem_key(req: ToolRequest, ns: Any = None) -> str:
    """幂等键统一在工具层派生（SPEC M3.5）。"""
    import hashlib
    import json

    ns_key = tuple(ns.as_tuple()) if ns is not None and hasattr(ns, "as_tuple") else ("",)
    payload = json.dumps(req.step.args, sort_keys=True, ensure_ascii=False, default=str)
    raw = f"{ns_key}:{req.step.index}:{req.step.tool_name}:{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def idempotency_layer(
    *,
    store: Any,
    key_fn: Callable[[ToolRequest, Any], str] | None = None,
    ns: Any = None,
) -> Layer:
    """插点 tool_call：命中幂等表直接回旧结果，**不执行任何副作用**（SPEC M7.2 C7）。"""

    derive = key_fn or default_idem_key

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ToolRequest):
                return await nxt(req)
            key = derive(req, ns)
            hit = await store.begin(ns, key)
            if hit is not None:
                return ToolResponse(result=hit.value)
            response = await nxt(req)
            if isinstance(response, ToolResponse) and response.result is not None:
                await store.commit(ns, key, _record(key, response.result))
            return response

        return handler

    return layer("idempotency", ["tool_call"], build, needs=["idempotency"], after=["approval"])


def _record(key: str, value: Any) -> Any:
    from harness.contracts.types import Recorded

    return Recorded(key=key, value=value)


# ------------------------------------------------------------------ Validate


def validate_layer(
    *,
    reflector: Any,
    max_retries: int = 2,
    budget: Budget | None = None,
) -> Layer:
    """插点 step：结果质量判定，按 Verdict 决定重跑还是采纳（SPEC M5.3）。

    修复计数落在 `Budget.retries`，不落在 State（不变量 2）。
    """

    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            if not isinstance(response, StepResponse) or reflector is None:
                return response
            state = getattr(req, "state", None)
            if state is None:
                return response

            for _ in range(max_retries + 1):
                result = state.data.get("last_result")
                verdict: Verdict = await reflector.review(result, state)
                if verdict.action != "retry":
                    return response
                if budget is not None:
                    if budget.retries >= max_retries:
                        break
                    budget.retries += 1
                response = await nxt(req)      # 重跑同一 step
            return response

        return handler

    return layer("validate", ["step"], build)


# ------------------------------------------------------------------ TaskBoard


def taskboard_layer() -> Layer:
    """插点 step + model_call：任务清单注入 + 状态推进（SPEC M13.4.1）。

    清单落在 `state.data["tasks"]`，由 `ModelFramer` 取成 `task` 槽（ephemeral）。
    """

    def build(nxt):
        async def handler(req):
            state = getattr(req, "state", None)
            if state is not None:
                board = state.section("tasks")
                board.setdefault("items", [])
                board["updated_at"] = time.time()
            return await nxt(req)

        return handler

    return layer("taskboard", ["step", "model_call"], build, after=["context"])


def add_task(state: Any, text: str, *, owner: str = "") -> dict:
    """三件套之一：建任务（上限 50，防模型无限建）。"""
    board = state.section("tasks")
    items = board.setdefault("items", [])
    if len(items) >= 50:
        raise ValueError("任务数已达上限 50")
    task = {
        "id": f"t{len(items) + 1}",
        "text": text,
        "status": "todo",
        "owner": owner,
    }
    items.append(task)
    return task


def update_task(state: Any, task_id: str, status: str, *, reason: str = "") -> dict:
    """三件套之二：改状态（todo → doing → done / blocked）。"""
    allowed = {"todo", "doing", "done", "blocked"}
    if status not in allowed:
        raise ValueError(f"非法状态：{status}")
    board = state.section("tasks")
    for task in board.get("items", []):
        if task["id"] == task_id:
            task["status"] = status
            if status == "blocked":
                task["reason"] = reason
            return task
    raise KeyError(f"未知任务：{task_id}")


def list_tasks(state: Any) -> list[dict]:
    """三件套之三：列任务。"""
    return list(state.section("tasks").get("items", []))


__all__ = [
    "context_layer",
    "checkpoint_layer",
    "budget_layer",
    "trace_layer",
    "approval_layer",
    "idempotency_layer",
    "validate_layer",
    "taskboard_layer",
    "state_namespace",
    "default_idem_key",
    "add_task",
    "update_task",
    "list_tasks",
]
