"""第 3 章产出：Agent Loop 的四道刹车。

不依赖真实模型即可运行（内置 FakeLLM），方便你专注观察"失控"本身。

四种失控对应的四种失控信号：
  1. 无限循环   ← 没有终止条件
  2. 重复调用   ← 相同参数反复调用同一工具
  3. 上下文爆炸 ← 历史无限增长
  4. 成本击穿   ← 没有预算
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------- 失控信号

@dataclass
class Budget:
    """预算三件套：步数、token、钱。任一耗尽即停。"""

    max_steps: int = 12
    max_tokens: int = 60_000
    max_cost: float = 0.05

    steps_used: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0

    def spend(self, tokens: int, cost: float) -> None:
        self.steps_used += 1
        self.tokens_used += tokens
        self.cost_used += cost

    def exhausted(self) -> str | None:
        if self.steps_used >= self.max_steps:
            return f"steps({self.max_steps})"
        if self.tokens_used >= self.max_tokens:
            return f"tokens({self.max_tokens})"
        if self.cost_used >= self.max_cost:
            return f"cost(¥{self.max_cost})"
        return None


@dataclass
class LoopGuard:
    """重复调用检测。

    关键洞察：模型"以为自己在探索"，实际在用同样参数调用同样的工具。
    这叫 thrash，是多步 Agent 最常见的浪费。
    """

    max_repeats: int = 2
    _seen: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def fingerprint(tool: str, args: dict[str, Any]) -> str:
        raw = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def check(self, tool: str, args: dict[str, Any]) -> str | None:
        """返回 None 表示放行，否则返回阻止原因。"""
        fp = self.fingerprint(tool, args)
        self._seen[fp] = self._seen.get(fp, 0) + 1
        if self._seen[fp] > self.max_repeats:
            return f"重复调用 {tool}({args}) 第 {self._seen[fp]} 次"
        return None


@dataclass
class ContextLimiter:
    """上下文裁剪：按 token 预算保留最近若干条消息。

    先做最简单的：保尾部。第 16 章会做更聪明的（摘要 + 固定槽位）。

    为什么单条消息也要截断？
    因为"一条消息 3000 token"这种情况（工具一次返回 200 条记录）在真实系统里极常见，
    只做"少留几条"根本压不住——3 条大消息就超预算了。
    """

    max_tokens: int = 4000
    per_message_cap: int = 800  # 单条消息的 token 上限

    def trim(
        self,
        messages: list[dict[str, Any]],
        est_tokens: Callable[[str], int],
        truncate: Callable[[str, int], str] | None = None,
    ) -> list[dict]:
        total, kept = 0, []
        for m in reversed(messages):
            content = str(m.get("content", ""))
            if truncate and est_tokens(content) > self.per_message_cap:
                content = truncate(content, self.per_message_cap)
            t = est_tokens(content)
            if total + t > self.max_tokens:
                break
            kept.append({**m, "content": content})
            total += t
        return list(reversed(kept))


# ---------------------------------------------------------------- 循环本身

@dataclass
class StepResult:
    done: bool
    output: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    cost: float = 0.0
    reason: str = ""
    observation: str | None = None  # 工具返回（用于模拟"观察结果把上下文撑爆"）


def truncate_tokens(text: str, max_tokens: int, est_tokens: Callable[[str], int]) -> str:
    """按 token 上限截断文本（保留头部与尾部，中间打省略号）。

    为什么保留尾部？因为工具返回的结论/错误信息通常在末尾。
    """
    t = est_tokens(text)
    if t <= max_tokens:
        return text
    keep_chars = int(len(text) * max_tokens / t)
    head = keep_chars // 2
    tail = keep_chars - head
    return f"{text[:head]}\n...<省略 {t - max_tokens} token>...\n{text[-tail:]}"


def run_loop(
    think: Callable[[list[dict], int], StepResult],
    act: Callable[[str, dict], str],
    budget: Budget,
    guard: LoopGuard,
    limiter: ContextLimiter,
    est_tokens: Callable[[str], int],
    truncate: Callable[[str, int], str] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """带四道刹车的 Agent Loop。

    注意顺序：每一步都先检查预算，再检查重复，最后才真正执行。
    反过来（先执行再检查）会让最后一次越界的调用真的发生。
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": "start"}]
    stop_reason = ""

    for step in range(budget.max_steps):
        # ① 预算检查（步数在本循环条件里，token/cost 在这里）
        hit = budget.exhausted()
        if hit:
            stop_reason = f"budget:{hit}"
            break

        # ④ 上下文裁剪：喂给模型之前先裁（含单条消息截断）
        ctx = limiter.trim(
            messages, est_tokens, truncate=lambda t, cap: truncate_tokens(t, cap, est_tokens)
        )
        if truncate is None:  # 对照组：不裁剪时保持原样
            ctx = messages
        ctx_tokens = sum(est_tokens(str(m.get("content", ""))) for m in ctx)

        # 输入侧的 token 也要花钱。这里用「输入 token 比输出便宜 4 倍」的常见比例估算，
        # 目的是让示例可复现地展示四种失控，而不是精确计费。
        res = think(ctx, step)
        input_tokens = ctx_tokens
        budget.spend(res.tokens + input_tokens, res.cost + input_tokens / 1e6 * 2)
        messages.append({"role": "assistant", "content": res.output})

        if verbose:
            print(
                f"[step {step}] in={input_tokens:>5} out={res.tokens:>5} "
                f"cost=¥{res.cost + input_tokens / 1e6 * 2:.6f} {res.reason}"
            )

        if res.done:
            stop_reason = "done"
            break

        # ② 重复调用检查
        blocked = False
        for call in res.tool_calls:
            why = guard.check(call["tool"], call.get("args", {}))
            if why:
                messages.append({"role": "tool", "content": f"BLOCKED: {why}，请换一种思路。"})
                stop_reason = f"guard:{why}"
                blocked = True
                break
            obs = res.observation if res.observation is not None else act(call["tool"], call.get("args", {}))
            messages.append({"role": "tool", "content": obs})
        if blocked:
            break

    if not stop_reason:
        stop_reason = f"budget:steps({budget.max_steps})"

    return {
        "stop_reason": stop_reason,
        "steps": budget.steps_used,
        "tokens": budget.tokens_used,
        "cost": round(budget.cost_used, 6),
        "messages": len(messages),
    }
