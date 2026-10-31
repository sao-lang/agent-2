"""第 38 章共用：脚本化 agent、成本记录、同一份任务数据。

不联网。每个 agent 调用都是一段固定剧本；记录调用次数、上下文字符与
估算 token，用来和第 33、35 章的手写版对账。
"""

from __future__ import annotations

from dataclasses import dataclass, field

CALL_MS = 1000
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
class Usage:
    calls: int = 0
    prompt_chars: int = 0
    tokens: int = 0
    ms: int = 0
    by_agent: dict[str, dict[str, int]] = field(default_factory=dict)

    def reset(self) -> None:
        self.calls = 0
        self.prompt_chars = 0
        self.tokens = 0
        self.ms = 0
        self.by_agent.clear()

    def add(self, agent: str, prompt: str) -> None:
        tokens = int(len(prompt) * TOKENS_PER_CHAR) + 20
        self.calls += 1
        self.prompt_chars += len(prompt)
        self.tokens += tokens
        self.ms += CALL_MS
        row = self.by_agent.setdefault(agent, {"calls": 0, "tokens": 0})
        row["calls"] += 1
        row["tokens"] += tokens


USAGE = Usage()


def reset() -> None:
    USAGE.reset()


def read_prompt(index: int) -> str:
    return (
        f"{'x' * SYSTEM}\n"
        "# 角色\n你是日志分析员，只负责一份日志。\n"
        "# 任务\n找出错误或隐患，按字段交回。\n"
        "# 输入\n<<<\n" + LOGS[index] + "\n>>>"
    )


def write_prompt(findings: list[str], evidence: list[str]) -> str:
    lines = [f"- [{e}] {f}" for f, e in zip(findings, evidence)]
    return (
        f"{'x' * SYSTEM}\n"
        "# 角色\n你是值班工程师，写一份事故初报。\n"
        "# 发现\n" + "\n".join(lines) + "\n# 输出\n三段：现象、根因、建议"
    )


def dispatch_prompt(done: int) -> str:
    return (
        f"{'x' * SYSTEM}\n"
        f"# 任务\n读三份日志并写报告。已完成 {done} 份，"
        f"决定下一个 worker。"
    )


def report(findings: list[str], evidence: list[str]) -> str:
    return "初报：" + "；".join(f"{f}（{e}）" for f, e in zip(findings, evidence))


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)
