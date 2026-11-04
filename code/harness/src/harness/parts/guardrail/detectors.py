"""护栏的检测器与仲裁（SPEC M9）。

**检测与动作分离**：检测器只报"哪一段、什么风险"，动作由策略层按环境决定。
仲裁规则定死：取最严动作；同级取最高 risk；rewrite 与 redact 冲突取 redact。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable, Sequence

from harness.contracts.status import Gate5, GuardrailAction
from harness.contracts.types import Content, GuardrailVerdict

#: 动作强度递增；仲裁取最大
ACTION_ORDER: tuple[str, ...] = (
    GuardrailAction.ALLOW,
    GuardrailAction.WARN,
    GuardrailAction.REDACT,
    GuardrailAction.REWRITE,
    GuardrailAction.ASK,
    GuardrailAction.BLOCK,
)


def _rank(action: str) -> int:
    try:
        return ACTION_ORDER.index(action)  # type: ignore[arg-type]
    except ValueError:
        return 0


def arbitrate(verdicts: Sequence[GuardrailVerdict]) -> GuardrailVerdict:
    """多个检测器的仲裁：最严动作胜出，同级取最高 risk。"""
    if not verdicts:
        return GuardrailVerdict()

    winner = max(verdicts, key=lambda v: (_rank(v.action), v.risk))
    labels: list[str] = []
    spans: list[tuple[int, int]] = []
    for v in verdicts:
        labels.extend(v.labels)
        spans.extend(v.spans)

    action = winner.action
    if action == GuardrailAction.REWRITE and any(
        v.action == GuardrailAction.REDACT for v in verdicts
    ):
        action = GuardrailAction.REDACT        # 改写可能引入新风险，脱敏更保守

    return GuardrailVerdict(
        risk=max(v.risk for v in verdicts),
        labels=tuple(dict.fromkeys(labels)),
        action=action,                          # type: ignore[arg-type]
        spans=tuple(spans),
        replacement=winner.replacement,
    )


def apply_verdict(text: str, verdict: GuardrailVerdict) -> str:
    """按仲裁结果改写文本（只有 redact/rewrite 会改内容）。"""
    if verdict.action not in (GuardrailAction.REDACT, GuardrailAction.REWRITE):
        return text
    if verdict.replacement is not None:
        return verdict.replacement
    out = text
    for start, end in sorted(verdict.spans, reverse=True):
        out = out[:start] + "[已脱敏]" + out[end:]
    return out


# ------------------------------------------------------------------ 检测器


class PatternGuardrail:
    """正则检测器基类：命中即报风险与区间，不动文本。"""

    name = "pattern"
    gates: frozenset[str] = frozenset({Gate5.INBOUND})
    action: str = GuardrailAction.WARN
    risk: float = 0.5

    def __init__(self, rules: Iterable[tuple[str, str]]) -> None:
        # rules: (label, pattern)
        self.rules = [(label, re.compile(pattern, re.IGNORECASE)) for label, pattern in rules]

    async def check(self, content: Content, scope=None) -> GuardrailVerdict:
        labels: list[str] = []
        spans: list[tuple[int, int]] = []
        for label, rx in self.rules:
            for match in rx.finditer(content.text):
                labels.append(label)
                spans.append((match.start(), match.end()))
        if not labels:
            return GuardrailVerdict()
        return GuardrailVerdict(
            risk=self.risk, labels=tuple(labels), action=self.action,  # type: ignore[arg-type]
            spans=tuple(spans),
        )


class InjectionGuardrail(PatternGuardrail):
    """间接注入的主战场：入站与入上下文两道闸（SPEC M9.1 ①②）。"""

    name = "injection"
    gates = frozenset({Gate5.INBOUND, Gate5.CONTEXT, Gate5.TOOL_OUT})
    action = GuardrailAction.BLOCK
    risk = 0.9

    def __init__(self) -> None:
        super().__init__(
            [
                ("ignore-instructions", r"ignore (all )?(previous|prior|above) instructions"),
                ("role-override", r"(you are now|act as|从现在起你是|你现在是)"),
                ("system-prompt", r"(system prompt|系统提示词|上面的指令)"),
                ("ignore-zh", r"(忽略|无视)(之前|以上|前面)的?(指令|要求)"),
            ]
        )


class PIIGuardrail(PatternGuardrail):
    """PII 检测：默认脱敏而不是拦截（拦了正常业务跑不动）。"""

    name = "pii"
    gates = frozenset({Gate5.CONTEXT, Gate5.MODEL_OUT, Gate5.OUTBOUND})
    action = GuardrailAction.REDACT
    risk = 0.6

    def __init__(self) -> None:
        super().__init__(
            [
                ("email", r"[\w.+-]+@[\w-]+\.[\w.]+"),
                ("phone", r"\b1[3-9]\d{9}\b"),
                ("id-card", r"\b\d{17}[\dXx]\b"),
                ("bank-card", r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
            ]
        )


class SecretLeakGuardrail(PatternGuardrail):
    """密钥泄漏：出口最后一公里，命中即拦。"""

    name = "secret_leak"
    gates = frozenset({Gate5.MODEL_OUT, Gate5.OUTBOUND, Gate5.TOOL_OUT})
    action = GuardrailAction.BLOCK
    risk = 1.0

    def __init__(self) -> None:
        super().__init__(
            [
                ("openai-key", r"\bsk-[A-Za-z0-9]{16,}\b"),
                ("aws-key", r"\bAKIA[0-9A-Z]{16}\b"),
                ("github-token", r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
                ("private-key", r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
            ]
        )


def builtin_detectors(names: Sequence[str]) -> list[PatternGuardrail]:
    """按名字装配检测器；未知名 → ConfigError（不静默跳过）。"""
    from harness.contracts.errors import ConfigError

    table = {
        "injection": InjectionGuardrail,
        "pii": PIIGuardrail,
        "secret_leak": SecretLeakGuardrail,
    }
    out = []
    for name in names:
        if name not in table:
            raise ConfigError(f"未知护栏：{name}；可用：{sorted(table)}")
        out.append(table[name]())
    return out


__all__ = [
    "ACTION_ORDER",
    "arbitrate",
    "apply_verdict",
    "PatternGuardrail",
    "InjectionGuardrail",
    "PIIGuardrail",
    "SecretLeakGuardrail",
    "builtin_detectors",
]
