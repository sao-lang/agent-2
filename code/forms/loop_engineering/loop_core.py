"""一个 agent 循环的工程骨架：六元组、四个插点、五种终止、JSONL 轨迹。

不联网，不 import 任何框架。策略与动作以函数传入，本文件不含模型调用。

四个插点（缺一个就有一类失败无法定位）：
    before_step(loop, obs, action) -> str | None   返回非空 = 否决，值即终止原因
    after_action(loop, action, result) -> None      副作用账本写在这里
    verify(loop, action, result) -> Verdict          外部裁判，不是模型自述
    on_exit(loop, reason) -> str                    出口，含降级交付

五种终止：completed / max_steps / budget / no_progress / repeated_action。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

TOKENS_PER_CHAR = 0.6          # 粗估，只用于相对比较，不是 tokenizer 实测


def digest(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Action:
    kind: str                  # read / write / send / finish ...
    target: str
    payload: str = ""

    def fingerprint(self) -> str:
        """同一动作换一个键序，指纹必须一致（第 6 章的 B4）。"""
        return digest({"kind": self.kind, "target": self.target, "payload": self.payload})


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""


@dataclass
class Limits:
    max_steps: int = 8
    max_tokens: int = 1600
    no_progress_after: int = 2
    repeat_after: int = 1


@dataclass
class Exit:
    reason: str                # 五种之一
    steps: int
    tokens: int
    delivered: str             # 交付物；降级时是部分产物
    degraded: bool


@dataclass
class Hooks:
    """四个插点。全为 None 等于一个裸 while 循环。"""
    before_step: Callable[["Loop", str, "Action | None"], str | None] | None = None
    after_action: Callable[["Loop", "Action", str], None] | None = None
    verify: Callable[["Loop", "Action | None", str], Verdict] | None = None
    on_exit: Callable[["Loop", str], str] | None = None


class Loop:
    """一次运行 = 一个实例。状态、账本、轨迹都属于实例，不共享。"""

    def __init__(self, run_id: str, policy: Callable[["Loop", str], "Action | None"],
                 act: Callable[["Loop", "Action"], str],
                 limits: Limits | None = None, hooks: Hooks | None = None,
                 trace_path: str | Path | None = None) -> None:
        self.run_id = run_id
        self.policy = policy
        self.act = act
        self.limits = limits or Limits()
        self.hooks = hooks or Hooks()
        self.state: dict[str, Any] = {}
        self.steps = 0
        self.tokens = 0
        self.records: list[dict[str, Any]] = []
        self.observation = ""
        self.last_result = "（还没有动作）"
        self.last_verdict = Verdict(False, "还没有校验")
        self.fp: Counter[str] = Counter()
        self.obs_hashes: deque[str] = deque(maxlen=max(2, self.limits.no_progress_after))
        self.trace_path = Path(trace_path) if trace_path else None
        self.task = ""

    def observe(self) -> str:
        self.observation = f"任务：{self.task}\n上一步结果：{self.last_result}"
        return self.observation

    def spend(self, text: str) -> None:
        self.tokens += int(len(text) * TOKENS_PER_CHAR)

    def record(self, phase: str, action: Action | None, verdict: Verdict) -> None:
        row = {
            "run_id": self.run_id,
            "step": self.steps,
            "phase": phase,
            "observation_hash": digest(self.observation),
            "action": f"{action.kind}:{action.target}" if action else "-",
            "action_hash": action.fingerprint() if action else "-",
            "verdict": verdict.reason or ("ok" if verdict.ok else "reject"),
            "state_digest": digest(self.state),
            "tokens": self.tokens,
        }
        self.records.append(row)

    def flush(self) -> None:
        if not self.trace_path:
            return
        with self.trace_path.open("a", encoding="utf-8") as f:
            for row in self.records[-1:]:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def run(self, task: str) -> Exit:
        self.task = task
        reason = "max_steps"
        while True:
            if self.steps >= self.limits.max_steps:
                reason = "max_steps"
                break
            outcome = step(self)
            if outcome is not None:
                reason = outcome
                break

        delivered = self.hooks.on_exit(self, reason) if self.hooks.on_exit else ""
        return Exit(reason, self.steps, self.tokens, delivered,
                    degraded=bool(delivered) and reason != "completed")


def step(lp: Loop) -> str | None:
    """走一步：观测 → 决策 → 插点 → 动作 → 账本 → 校验。返回终止原因或 None。"""
    obs = lp.observe()
    lp.obs_hashes.append(digest(obs))
    stalled = (len(lp.obs_hashes) == lp.obs_hashes.maxlen
               and len(set(lp.obs_hashes)) == 1)
    if stalled:
        return "no_progress"

    action = lp.policy(lp, obs)
    lp.spend(obs)

    if lp.hooks.before_step:                       # 插点一：动作之前，唯一能否决的位置
        veto = lp.hooks.before_step(lp, obs, action)
        if veto:
            return veto

    if action is None:                             # 策略说"完成了"，交给裁判
        verdict = (lp.hooks.verify(lp, None, lp.last_result)   # 插点三
                   if lp.hooks.verify else Verdict(True, "无裁判，采信自述"))
        lp.record("finish", None, verdict)
        if verdict.ok:
            return "completed"
        lp.last_result = f"裁判拒绝：{verdict.reason}"
        lp.steps += 1
        return None

    lp.steps += 1
    result = lp.act(lp, action)
    lp.spend(result)
    if lp.hooks.after_action:                      # 插点二：动作之后，副作用账本
        lp.hooks.after_action(lp, action, result)
    verdict = (lp.hooks.verify(lp, action, result)             # 插点三
               if lp.hooks.verify else Verdict(True, ""))
    lp.last_verdict = verdict
    lp.last_result = result
    lp.record("act", action, verdict)
    lp.flush()
    return None


def show_trace(exits: list[Exit]) -> None:
    """把轨迹打成一行一步的紧凑视图，便于对照两次运行。"""
    for ex in exits:
        flag = "降级" if ex.degraded else ("完成" if ex.reason == "completed" else "未完成")
        print(f"    {ex.reason:<15} 步数={ex.steps} tokens={ex.tokens} 交付={len(ex.delivered):>4}字 {flag}")
