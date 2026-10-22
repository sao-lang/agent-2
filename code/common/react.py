"""第 57 章产出：ReAct 的三种实现，用来做对照实验。

为什么要实现三遍？
  · 手写文本解析版 —— 让你看见 ReAct 的本质（就是"思考-行动-观察"拼成文本再解析）
  · 原生 tool_calls 版 —— 现代做法，结构化
  · 带刹车版 —— 把第 58 章的四道刹车接上去

三遍都跑同一个任务，你就能回答"为什么现在没人手写 ReAct 文本解析了"。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from common.guards import Budget, ContextLimiter, LoopGuard, truncate_tokens


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


# ============================================================ 方式一：手写文本 ReAct

REACT_PROMPT = """你是一个会使用工具的助手。请严格按照下面的格式回答。

可用工具：
{tools}

格式要求（不要输出多余内容）：
Thought: 你的思考
Action: 工具名
Action Input: 工具参数的 JSON
（系统会返回 Observation，然后你继续 Thought）

当你已经能回答时，用：
Thought: 我已经知道答案了
Final Answer: 你的最终回答

用户问题：{question}
{history}"""


@dataclass
class TextReAct:
    """纯文本 ReAct：靠正则解析模型的输出。

    这就是 2022 年 ReAct 论文的原始形态，也是各框架早期的实现方式。
    """

    llm_call: Callable[[str], str]
    tools: dict[str, Callable[[dict], str]]
    max_steps: int = 6
    verbose: bool = True

    def run(self, question: str) -> dict[str, Any]:
        history = ""
        trace: list[dict[str, Any]] = []

        for step in range(self.max_steps):
            prompt = REACT_PROMPT.format(
                tools="\n".join(f"- {n}: {_sig(f)}" for n, f in self.tools.items()),
                question=question,
                history=history,
            )
            raw = self.llm_call(prompt)
            if self.verbose:
                print(f"\n--- step {step} raw output ---\n{raw}")

            if "Final Answer:" in raw:
                answer = raw.split("Final Answer:", 1)[1].strip()
                trace.append({"step": step, "type": "final", "raw": raw})
                return {"answer": answer, "steps": step + 1, "trace": trace, "ok": True}

            action = _parse(raw, r"Action:\s*(.+)")
            action_input = _parse(raw, r"Action Input:\s*(.+?)(?:\n[A-Z]|$)", dotall=True)

            if not action:
                # ← 经典失败点：模型没按格式输出，整个循环就卡住了
                history += f"\n{raw}\nObservation: 格式错误，请严格使用 Thought/Action/Action Input 格式。\n"
                trace.append({"step": step, "type": "format_error", "raw": raw})
                continue

            tool = self.tools.get(action.strip())
            if not tool:
                obs = f"错误：没有名为 {action} 的工具"
            else:
                try:
                    args = json.loads(action_input.strip()) if action_input else {}
                except json.JSONDecodeError:
                    args = {"_raw": action_input}
                obs = tool(args)

            trace.append({"step": step, "type": "action", "action": action, "args": action_input, "obs": obs})
            history += f"\n{raw}\nObservation: {obs}\n"
            if self.verbose:
                print(f"Observation: {obs}")

        return {"answer": "", "steps": self.max_steps, "trace": trace, "ok": False}


def _parse(text: str, pattern: str, dotall: bool = False) -> str | None:
    flags = re.DOTALL if dotall else 0
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _sig(fn: Callable) -> str:
    return (fn.__doc__ or "无说明").strip().splitlines()[0]


# ============================================================ 方式二：原生 tool_calls

def react_native(llm, tools: list, question: str, max_steps: int = 6) -> dict[str, Any]:
    """现代做法：让模型直接产出结构化的 tool_calls，不用解析文本。

    和文本版的三个本质区别：
      1. 参数是 JSON 对象，不是待解析的字符串（不会出现 JSON 解析失败）
      2. 工具选择是协议的字段，不是正则匹配（不会因为多写一个字就失效）
      3. 支持一次返回多个 tool_calls（并行调用）
    """
    llm_with_tools = llm.bind_tools(tools)
    by_name = {t.name: t for t in tools}
    messages: list[Any] = [("user", question)]

    for step in range(max_steps):
        ai = llm_with_tools.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return {"answer": ai.content, "steps": step + 1, "ok": True, "messages": messages}

        for call in ai.tool_calls:
            fn = by_name[call["name"]]
            result = fn.invoke(call["args"])
            messages.append(
                # 必须带上 tool_call_id，否则下一轮模型对不上号
                {"role": "tool", "content": str(result), "tool_call_id": call["id"]}
            )

    return {"answer": "", "steps": max_steps, "ok": False, "messages": messages}


# ============================================================ 方式三：ReAct + 刹车

@dataclass
class SafeReAct:
    """把第 58 章的四道刹车接到 tool_calls 版上。

    这一版是本书之后所有 Agent 的基础形态。
    """

    llm: Any
    tools: list
    budget: Budget = field(default_factory=lambda: Budget(max_steps=8, max_tokens=40_000, max_cost=0.02))
    guard: LoopGuard = field(default_factory=lambda: LoopGuard(max_repeats=2))
    limiter: ContextLimiter = field(default_factory=lambda: ContextLimiter(max_tokens=6000))

    def run(self, question: str) -> dict[str, Any]:
        from common.meter import usage_of

        llm_with_tools = self.llm.bind_tools(self.tools)
        by_name = {t.name: t for t in self.tools}
        messages: list[Any] = [("user", question)]
        stop_reason = ""

        while True:
            hit = self.budget.exhausted()
            if hit:
                stop_reason = f"budget:{hit}"
                break

            trimmed = self.limiter.trim(
                [{"role": "m", "content": str(m)} for m in messages],
                est_tokens,
                truncate=lambda t, cap: truncate_tokens(t, cap, est_tokens),
            )

            ai = llm_with_tools.invoke(messages)
            u = usage_of(ai)
            self.budget.spend(u["input_tokens"] + u["output_tokens"], u["input_tokens"] / 1e6 * 2 + u["output_tokens"] / 1e6 * 8)
            messages.append(ai)

            if not ai.tool_calls:
                stop_reason = "answer"
                return {
                    "answer": ai.content,
                    "steps": self.budget.steps_used,
                    "cost": round(self.budget.cost_used, 6),
                    "ok": True,
                    "stop_reason": stop_reason,
                    "trimmed_messages": len(trimmed),
                }

            for call in ai.tool_calls:
                blocked = self.guard.check(call["name"], call["args"])
                if blocked:
                    messages.append({"role": "tool", "content": f"BLOCKED: {blocked}", "tool_call_id": call["id"]})
                    stop_reason = f"guard:{blocked}"
                    continue
                try:
                    out = str(by_name[call["name"]].invoke(call["args"]))
                except Exception as e:  # noqa: BLE001
                    out = f"TOOL_ERROR: {type(e).__name__}: {e}"
                messages.append({"role": "tool", "content": out, "tool_call_id": call["id"]})

        return {
            "answer": "",
            "steps": self.budget.steps_used,
            "cost": round(self.budget.cost_used, 6),
            "ok": False,
            "stop_reason": stop_reason,
        }
