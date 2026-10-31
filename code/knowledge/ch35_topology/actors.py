"""第 35 章共用的脚本化 actor、虚拟时钟与交接单。

不联网。所有 actor 都是固定剧本，只统计调用次数、上下文大小与虚拟耗时，
不判断答案质量。这样四种拓扑可以在同一任务上直接比较。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

CALL_MS = 1000
HANDOFF_MS = 200
TOKENS_PER_CHAR = 0.6
SYSTEM = 180

LOGS = {
    1: "12:00:01 ERROR pool exhausted at db.py:42; 12:00:02 retry 1/∞",
    2: "12:00:03 WARN retry without max_attempts at client.py:88",
    3: "12:00:05 INFO timeout=0 configured at config.py:17 (means no timeout)",
}

FINDINGS = {
    1: "连接池在 db.py:42 耗尽，重试没有上限",
    2: "client.py:88 的重试没有 max_attempts",
    3: "config.py:17 把 timeout 设成 0，等于不超时",
}

EVIDENCE = {1: "db.py:42", 2: "client.py:88", 3: "config.py:17"}


@dataclass
class Brief:
    """交接单：子 agent 交回的东西不是一段话，而是一张可判定的表。"""

    task: str
    result: str
    evidence: str
    confidence: str = "high"
    open_items: list[str] = field(default_factory=list)
    usage_tokens: int = 0


@dataclass
class Span:
    span_id: str
    parent: str | None
    agent: str
    purpose: str
    prompt_chars: int
    reply_chars: int
    start_ms: int
    end_ms: int


@dataclass
class World:
    now_ms: int = 0
    calls: int = 0
    handoffs: int = 0
    tokens: int = 0
    spans: list[Span] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def tick(self) -> int:
        self.now_ms += CALL_MS
        return self.now_ms


@dataclass
class Actor:
    name: str
    world: World
    trace_id: str = "run-1"
    last_span_id: str = ""

    def run(self, prompt: str, purpose: str, reply: str,
            parent: str | None = None) -> str:
        start = self.world.now_ms
        end = self.world.tick()
        tokens = int(len(prompt) * TOKENS_PER_CHAR) + 20
        self.world.calls += 1
        self.world.tokens += tokens
        span = Span(
            span_id=f"s{next(self.world._ids)}",
            parent=parent,
            agent=self.name,
            purpose=purpose,
            prompt_chars=len(prompt),
            reply_chars=len(reply),
            start_ms=start,
            end_ms=end,
        )
        self.world.spans.append(span)
        self.last_span_id = span.span_id
        return reply


def reader_prompt(index: int, log: str) -> str:
    return (
        f"{'x' * SYSTEM}\n"
        "# 角色\n你是日志分析员，只负责一份日志。\n"
        "# 任务\n找出这份日志里的错误或隐患，按字段交回。\n"
        "# 输入\n<<<\n" + log + "\n>>>\n"
        "# 输出\nresult / evidence / confidence"
    )


def read_log(actor: Actor, index: int, parent: str | None = None) -> Brief:
    log = LOGS[index]
    prompt = reader_prompt(index, log)
    actor.run(prompt, f"读日志 {index}", FINDINGS[index], parent)
    return Brief(
        task=f"分析日志 {index}",
        result=FINDINGS[index],
        evidence=EVIDENCE[index],
        usage_tokens=int(len(prompt) * TOKENS_PER_CHAR) + 20,
    )


def writer_prompt(briefs: list[Brief]) -> str:
    lines = [f"- [{b.evidence}] {b.result}（置信 {b.confidence}）" for b in briefs]
    return (
        f"{'x' * SYSTEM}\n"
        "# 角色\n你是值班工程师，把发现写成一份事故初报。\n"
        "# 已确认的发现\n" + "\n".join(lines) + "\n"
        "# 输出\n三段：现象、根因、建议"
    )


def write_report(actor: Actor, briefs: list[Brief], parent: str | None = None) -> str:
    joined = "；".join(b.result for b in briefs)
    return actor.run(writer_prompt(briefs), "写报告", f"初报：{joined}", parent=parent)


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def print_spans(world: World) -> None:
    print("  span  父    agent        动作              输入   输出")
    for s in world.spans:
        print(f"  {pad(s.span_id, 5)}{pad(s.parent or '-', 5)}"
              f"{pad(s.agent, 13)}{pad(s.purpose, 18)}"
              f"{s.prompt_chars:<6}{s.reply_chars}")
