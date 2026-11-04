"""五个薄层（SPEC M13.4）：Tenancy / Audit / Retrieval / MemoryRecall / MemoryWrite。"""

from __future__ import annotations

import time
from typing import Any

from harness.contracts.events import RunEvent
from harness.contracts.types import ModelRequest, RunRequest, StepRequest
from harness.parts.middleware.base import Layer, layer
from harness.parts.middleware.builtin import state_namespace


# ------------------------------------------------------------------ Tenancy


def tenancy_layer(*, expected_tenant: str | None = None) -> Layer:
    """插点 run：绑定命名空间，拒绝越权会话（SPEC M13.4 #1）。"""

    def build(nxt):
        async def handler(req):
            if isinstance(req, RunRequest):
                ns = req.ns
                if expected_tenant and ns.tenant != expected_tenant:
                    from harness.contracts.errors import PolicyError

                    raise PolicyError(f"租户不匹配：{ns.tenant} != {expected_tenant}")
                state = getattr(req, "state", None)
                if state is not None:
                    state.session = state.session.__class__(
                        session_id=state.session.session_id,
                        tenant=ns.tenant or state.session.tenant,
                        started_at=state.session.started_at,
                    )
            return await nxt(req)

        return handler

    return layer("tenancy", ["run"], build)


def bind_namespace(req: Any) -> Any:
    """工具：从请求里取命名空间（作用域缺省时的兜底）。"""
    ns = getattr(req, "ns", None)
    if ns is not None:
        return ns
    state = getattr(req, "state", None)
    return state_namespace(state) if state is not None else None


# ------------------------------------------------------------------ Audit


def audit_layer(*, sink: Any) -> Layer:
    """全部插点：结构化审计（谁、做了什么、结果摘要、用量）（SPEC M13.4 #4）。"""

    def build(nxt):
        async def handler(req):
            name = type(req).__name__
            started = time.time()
            response = await nxt(req)
            try:
                await sink.emit(
                    RunEvent(
                        name="audit",
                        ts_ms=int(time.time() * 1000),
                        fields={
                            "request": name,
                            "tool": getattr(getattr(req, "step", None), "tool_name", ""),
                            "ok": getattr(getattr(response, "result", None), "ok", None),
                            "elapsed_ms": int((time.time() - started) * 1000),
                        },
                    )
                )
            except Exception:  # noqa: BLE001 - 审计不得影响请求
                pass
            return response

        return handler

    return layer("audit", ["run", "step", "model_call", "tool_call"], build,
                 needs=["events"], after=["trace"])


# ------------------------------------------------------------------ Retrieval


def retrieval_layer(*, knowledge: Any, ns: Any = None, k: int = 6) -> Layer:
    """插点 model_call：召回候选写进 `state.data["retrieved"]`（SPEC M13.4 #9）。

    只给候选、不决定条数以外的裁剪——裁剪在取景器里（Memory 不感知预算）。
    """

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ModelRequest) or req.state is None:
                return await nxt(req)
            state = req.state
            if not state.data.get("retrieved"):           # 一轮只检索一次
                query = state.goal.text
                items = await knowledge.retrieve(query, k=k)
                state.data["retrieved"] = items
            return await nxt(req)

        return handler

    return layer("retrieval", ["model_call"], build, needs=["index"], before=["context"])


# ------------------------------------------------------------------ Memory recall


def memory_recall_layer(*, memory: Any, layers: tuple[str, ...] = ("semantic", "episodic"),
                        k: int = 6) -> Layer:
    """插点 model_call：跨会话召回写进 `state.data["memory"]`（SPEC M13.4 #10）。"""

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ModelRequest) or req.state is None:
                return await nxt(req)
            state = req.state
            if not state.data.get("memory"):
                items = await memory.recall(
                    query=state.goal.text,
                    scope=state.goal.user_id,
                    layers=list(layers),
                    k=k,
                )
                state.data["memory"] = items
            return await nxt(req)

        return handler

    return layer("memory_recall", ["model_call"], build, needs=["memory"], before=["context"])


# ------------------------------------------------------------------ Memory write


def memory_write_layer(*, memory: Any, policy: Any) -> Layer:
    """插点 run：出口后按 MemoryPolicy 写入（SPEC M13.4 #11）。"""

    def build(nxt):
        async def handler(req):
            response = await nxt(req)
            state = getattr(req, "state", None)
            # run 点拿到的是 RunResult；若被包成 RunResponse 则取其 result
            outcome = response.result if hasattr(response, "result") else response
            if state is None or outcome is None:
                return response
            try:
                if await policy.should_write(state, outcome):
                    items = await policy.extract(state)
                    if items:
                        await memory.write(items)
            except Exception:  # noqa: BLE001 - 记忆写入失败不影响主流程
                pass
            return response

        return handler

    return layer("memory_write", ["run"], build, needs=["memory"], after=["delivery"])


__all__ = [
    "tenancy_layer",
    "bind_namespace",
    "audit_layer",
    "retrieval_layer",
    "memory_recall_layer",
    "memory_write_layer",
]
