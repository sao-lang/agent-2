"""第 41 章 · handoff、护栏与会话的协议形态（原理演示，不是 Agents SDK 的 API）。

运行：
    $env:PYTHONPATH="$PWD\\.libs"; $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch41_frameworks/handoff_protocol.py

不联网、不调模型。两个脚本化 agent 用固定剧本演示三件事：
交接时控制权怎么转、转过去以后上下文剩下多少、护栏插在哪两个位置。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Turn:
    role: str
    text: str


@dataclass
class Session:
    """会话：跨运行保留的消息列表。框架里这东西叫 session / thread。"""

    turns: list[Turn] = field(default_factory=list)

    def add(self, role: str, text: str) -> None:
        self.turns.append(Turn(role, text))

    def window(self, n: int = 3) -> list[Turn]:
        """交给模型的上下文窗口：只取最近 n 轮。"""
        return self.turns[-n:]


def triage(turns: list[Turn]) -> dict:
    """分诊 agent：只做判断，不处理业务。"""
    last = turns[-1].text
    if "退" in last or "退款" in last:
        return {"kind": "handoff", "to": "refund", "reason": "涉及退货，转售后专员"}
    return {"kind": "final", "text": "这个问题我直接回答：请查看帮助中心。"}


def refund(turns: list[Turn]) -> dict:
    """售后 agent：给结论。问题里提到赔偿时给一句超额承诺，用来触发输出护栏。"""
    if any("赔" in t.text for t in turns):
        return {"kind": "final", "text": "未拆封且在十五天内，可以退货；另外赔偿 500 元。"}
    return {"kind": "final", "text": "未拆封且在十五天内，可以退货，运费由商家承担。"}


AGENTS = {"triage": triage, "refund": refund}


def guard_input(text: str) -> str | None:
    """输入护栏：命中就拦，不进模型。"""
    if "身份证" in text:
        return "输入含敏感信息，请脱敏后再提交"
    return None


def guard_output(text: str) -> str | None:
    """输出护栏：命中就转人工，不直接返回。"""
    if "赔偿" in text:
        return "回答包含金额承诺，转人工复核"
    return None


def run(user_text: str, session: Session, max_handoffs: int = 2) -> tuple[str, list[str]]:
    trace: list[str] = []
    blocked = guard_input(user_text)
    if blocked:
        trace.append(f"输入护栏拦截：{blocked}")
        return blocked, trace

    session.add("user", user_text)
    trace.append(f"会话轮数：{len(session.turns)}")
    current = "triage"
    for _ in range(max_handoffs + 1):
        ctx = session.window()
        trace.append(f"{current} 收到 {len(ctx)} 轮上下文（会话共 {len(session.turns)} 轮，丢弃 {len(session.turns) - len(ctx)} 轮）")
        reply = AGENTS[current](ctx)
        if reply["kind"] == "handoff":
            trace.append(f"交接：{current} → {reply['to']}，理由 {reply['reason']!r}")
            session.add("handoff", f"{current} 转给 {reply['to']}：{reply['reason']}")
            current = reply["to"]
            continue
        out = guard_output(reply["text"])
        if out:
            trace.append(f"输出护栏拦截：{out}")
            session.add("assistant", "[转人工]")
            return out, trace
        session.add("assistant", reply["text"])
        return reply["text"], trace
    return "交接次数超限", trace


def main() -> None:
    session = Session()
    print("=== 1. 一次带交接的运行 ===")
    text, trace = run("这个订单能退吗", session)
    for line in trace:
        print("  " + line)
    print(f"  最终输出：{text}")
    print(f"  会话轮数：{len(session.turns)}，角色序列：{[t.role for t in session.turns]}")

    print("=== 2. 同一会话里再问一次 ===")
    text, trace = run("那发票能重开吗", session)
    for line in trace:
        print("  " + line)
    print(f"  最终输出：{text}")
    print(f"  会话轮数：{len(session.turns)}")

    print("=== 3. 输入护栏 ===")
    text, trace = run("我的身份证是 3301…，能退吗", session)
    for line in trace:
        print("  " + line)
    print(f"  会话轮数没变：{len(session.turns)}")

    print("=== 4. 输出护栏 ===")
    text, trace = run("质量问题退货怎么赔", Session())
    for line in trace:
        print("  " + line)
    print(f"  最终输出：{text}")


if __name__ == "__main__":
    main()
