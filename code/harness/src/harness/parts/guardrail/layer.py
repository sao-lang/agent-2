"""护栏层（SPEC M9.2 / M13.4 #13 #14）：输入两道闸 + 输出两道闸。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from harness.contracts.errors import PolicyError
from harness.contracts.events import RunEvent
from harness.contracts.status import Gate5, GuardrailAction
from harness.contracts.types import (
    Content,
    GuardrailVerdict,
    ModelRequest,
    ModelResponse,
    RunRequest,
)
from harness.parts.guardrail.detectors import apply_verdict, arbitrate
from harness.parts.middleware.base import Layer, layer

INPUT_GATES = (Gate5.INBOUND, Gate5.CONTEXT)
OUTPUT_GATES = (Gate5.MODEL_OUT, Gate5.OUTBOUND)


async def _scan(
    guardrails: Sequence[Any],
    content: Content,
    *,
    gates: Sequence[str],
    sink: Any = None,
    fail_open: bool = False,
) -> GuardrailVerdict:
    """逐个检测器扫描并仲裁；检测器自身失败默认 fail-closed。"""
    verdicts: list[GuardrailVerdict] = []
    for rule in guardrails:
        rule_gates = {str(g) for g in getattr(rule, "gates", ())}
        if not rule_gates & {str(g) for g in gates}:
            continue
        try:
            verdicts.append(await rule.check(content, None))
        except Exception as exc:  # noqa: BLE001 - 检测器故障
            verdicts.append(
                GuardrailVerdict(
                    risk=1.0,
                    labels=(f"detector_error:{getattr(rule, 'name', '?')}",),
                    action=("warn" if fail_open else "block"),  # type: ignore[arg-type]
                )
            )
            _ = exc

    verdict = arbitrate(verdicts)
    if verdict.action != GuardrailAction.ALLOW and sink is not None:
        try:
            await sink.emit(
                RunEvent(
                    name="guardrail",
                    fields={
                        "content_kind": content.kind,
                        "labels": list(verdict.labels),
                        "action": str(verdict.action),
                        "risk": verdict.risk,
                    },
                )
            )
        except Exception:  # noqa: BLE001 - 审计不得影响请求
            pass
    return verdict


def input_guard_layer(
    *,
    guardrails: Sequence[Any],
    sink: Any = None,
    fail_open: bool = False,
) -> Layer:
    """插点 model_call：扫入站消息与入上下文的检索/记忆/skill（闸 ①②）。"""

    def build(nxt):
        async def handler(req):
            if not isinstance(req, ModelRequest):
                return await nxt(req)

            messages = list(req.messages)
            for index, message in enumerate(messages):
                verdict = await _scan(
                    guardrails,
                    Content(text=str(message.get("content", "")), kind="user", ref=f"msg:{index}"),
                    gates=INPUT_GATES,
                    sink=sink,
                    fail_open=fail_open,
                )
                if verdict.action == GuardrailAction.BLOCK:
                    raise PolicyError(f"输入被拦截：{','.join(verdict.labels)}")
                if verdict.action in (GuardrailAction.REDACT, GuardrailAction.REWRITE):
                    messages[index] = {
                        **message,
                        "content": apply_verdict(str(message.get("content", "")), verdict),
                    }

            # 闸 ②：入上下文的检索资料 / 记忆 / 技能正文——间接注入的主战场
            state = getattr(req, "state", None)
            if state is not None:
                for key in ("retrieved", "memory"):
                    items = list(state.data.get(key) or [])
                    if not items:
                        continue
                    scanned = []
                    for item in items:
                        text = getattr(item, "text", None)
                        if text is None:
                            scanned.append(item)
                            continue
                        verdict = await _scan(
                            guardrails,
                            Content(text=text, kind=key, ref=getattr(item, "source", "")),
                            gates=(Gate5.CONTEXT,),
                            sink=sink,
                            fail_open=fail_open,
                        )
                        if verdict.action == GuardrailAction.BLOCK:
                            raise PolicyError(f"{key} 内容被拦截：{','.join(verdict.labels)}")
                        if verdict.action in (GuardrailAction.REDACT, GuardrailAction.REWRITE):
                            item = replace(item, text=apply_verdict(text, verdict))
                        scanned.append(item)
                    state.data[key] = scanned

            return await nxt(replace(req, messages=tuple(messages)))

        return handler

    return layer("input_guard", ["model_call"], build, after=["context"], needs=["guardrails"])


def output_guard_layer(
    *,
    guardrails: Sequence[Any],
    sink: Any = None,
    fail_open: bool = False,
) -> Layer:
    """插点 model_call + run：扫模型回复与最终答案（闸 ③⑤）。"""

    def build(nxt):
        async def handler(req):
            from harness.contracts.result import RunResult

            response = await nxt(req)

            if isinstance(response, ModelResponse) and response.reply is not None:
                verdict = await _scan(
                    guardrails,
                    Content(text=response.reply.content, kind="model"),
                    gates=OUTPUT_GATES,
                    sink=sink,
                    fail_open=fail_open,
                )
                if verdict.action == GuardrailAction.BLOCK:
                    raise PolicyError(f"模型输出被拦截：{','.join(verdict.labels)}")
                if verdict.action in (GuardrailAction.REDACT, GuardrailAction.REWRITE):
                    reply = replace(
                        response.reply,
                        content=apply_verdict(response.reply.content, verdict),
                    )
                    return replace(response, reply=reply)
                return response

            if isinstance(response, RunResult) and response.answer:
                verdict = await _scan(
                    guardrails,
                    Content(text=response.answer, kind="answer"),
                    gates=OUTPUT_GATES,
                    sink=sink,
                    fail_open=fail_open,
                )
                if verdict.action == GuardrailAction.BLOCK:
                    return replace(
                        response,
                        answer="[已拦截] 输出包含敏感信息",
                        error=f"guardrail_blocked:{','.join(verdict.labels)}",
                    )
                if verdict.action in (GuardrailAction.REDACT, GuardrailAction.REWRITE):
                    return replace(response, answer=apply_verdict(response.answer, verdict))
            return response

        return handler

    return layer("output_guard", ["model_call", "run"], build,
                 after=["context"], needs=["guardrails"])


__all__ = ["input_guard_layer", "output_guard_layer", "INPUT_GATES", "OUTPUT_GATES"]
