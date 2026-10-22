"""第 16 章 · 第 5 级：四道刹车合体，并回答"为什么停"。

运行：
    python code/ch16_loop/step5_all_four.py

这一级把第 1~4 级拼起来，另外加两个东西：
  · **停止原因可读**（不是 True/False，而是"因为什么停的"）
  · **剩余预算写进提示**（让模型自己收敛，比硬拦更省）

四个实验用同一个有毛病的模型（ScriptedBrain），只改变"开了几道刹车"。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

PRICE_PER_1K_TOKENS = 0.002


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


def truncate_tokens(text: str, max_tokens: int) -> str:
    """按估算比例等比截断，保留头尾。"""
    t = est_tokens(text)
    if t <= max_tokens:
        return text
    keep = int(len(text) * max_tokens / t)
    return f"{text[:keep // 2]}\n...<省略约 {t - max_tokens} token>...\n{text[-(keep - keep // 2):]}"


@dataclass
class Budget:
    max_steps: int = 12
    max_tokens: int = 60_000
    max_cost: float = 0.05
    steps_used: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0

    def spend(self, input_tokens: int, output_tokens: int) -> None:
        self.steps_used += 1
        self.tokens_used += input_tokens + output_tokens
        self.cost_used += (input_tokens + output_tokens) / 1000 * PRICE_PER_1K_TOKENS

    def exhausted(self) -> str | None:
        if self.steps_used >= self.max_steps:
            return f"steps({self.max_steps})"
        if self.tokens_used >= self.max_tokens:
            return f"tokens({self.max_tokens})"
        if self.cost_used >= self.max_cost:
            return f"cost(¥{self.max_cost})"
        return None

    def left(self) -> str:
        return (f"剩余 {self.max_steps - self.steps_used} 步 / "
                f"{self.max_tokens - self.tokens_used:,} token / "
                f"¥{self.max_cost - self.cost_used:.4f}")


@dataclass
class LoopGuard:
    max_repeats: int = 2
    _seen: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def fingerprint(tool: str, args: dict) -> str:
        raw = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def check(self, tool: str, args: dict) -> str | None:
        fp = self.fingerprint(tool, args)
        self._seen[fp] = self._seen.get(fp, 0) + 1
        if self._seen[fp] > self.max_repeats:
            return f"重复调用 {tool}({args}) 第 {self._seen[fp]} 次"
        return None


@dataclass
class ContextLimiter:
    max_tokens: int = 4000
    per_message_cap: int = 800

    def trim(self, messages: list[str]) -> list[str]:
        kept, total = [], 0
        for m in reversed(messages):
            m = truncate_tokens(m, self.per_message_cap)
            t = est_tokens(m)
            if total + t > self.max_tokens:
                break
            kept.append(m)
            total += t
        return list(reversed(kept))


@dataclass
class StepResult:
    done: bool
    output: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    observation: str = ""
    out_tokens: int = 0


class ScriptedBrain:
    """一个"会犯所有毛病"的模型。同一个剧本跑四种配置，才能做对照。

    剧本：
      第 1~2 轮  查资料，工具返回一大坨（撑上下文）
      第 3~5 轮  "再确认一次"，参数完全相同（重复调用）
      第 6~8 轮  超长输出"深度分析"（成本击穿）
      第 9 轮    给出答案
    """

    def __init__(self) -> None:
        self.n = 0
        self._rechecked = 0

    def think(self, ctx: list[str]) -> StepResult:
        self.n += 1

        # 模型"看到"被拦截的提示后，会提前收尾 —— 这是真实的模型行为
        if any("BLOCKED" in c for c in ctx) and self._rechecked == 0:
            self._rechecked = 1
            return StepResult(True, "不重复了，直接给答案：销量环比下降 3%。", out_tokens=40)

        if self.n == 1:
            return StepResult(False, "先看数据", "fetch", {"url": "doc/1"},
                              "检索结果：" + "内容" * 500, 60)
        if self.n == 2:
            return StepResult(False, "再看另一份", "fetch", {"url": "doc/2"},
                              "检索结果：" + "内容" * 500, 60)
        if self.n <= 5:
            return StepResult(False, "再确认一次", "search", {"q": "销量"}, "3 条结果", 40)
        if self.n <= 8:
            return StepResult(False, "深度分析：" + "细节" * 1500, "", {}, "", 3000)
        return StepResult(True, "销量环比下降 3%。", out_tokens=40)


def run(*, budget: Budget, guard: LoopGuard, limiter: ContextLimiter,
        show_prompt_budget: bool) -> dict:
    history = ["用户：分析上季度销量"]
    brain = ScriptedBrain()

    while True:  # 只靠模型剧本与刹车退出，不设额外兜底，才看得出刹车的作用
        hit = budget.exhausted()
        if hit:
            return {"steps": budget.steps_used, "tokens": budget.tokens_used,
                    "cost": budget.cost_used, "stop": f"budget:{hit}"}

        ctx = limiter.trim(history)
        if show_prompt_budget:
            ctx = ctx + [f"[系统提示] {budget.left()}"]

        res = brain.think(ctx)
        budget.spend(sum(est_tokens(c) for c in ctx), res.out_tokens)
        history.append(res.output)

        if res.done:
            return {"steps": budget.steps_used, "tokens": budget.tokens_used,
                    "cost": budget.cost_used, "stop": "done"}

        why = guard.check(res.tool, res.args)
        if why:
            history.append(f"[工具] BLOCKED: {why}，请换一种思路。")
            continue
        if res.observation:
            history.append(f"[工具] {res.observation}")


def main() -> None:
    print("=" * 78)
    print("第 5 级：四道刹车合体（每一行比上一行多一道）")
    print("=" * 78)

    OFF = 10**9
    variants = [
        ("裸循环（无刹车）", OFF, OFF, OFF, OFF, OFF),
        ("+ 预算（步数 6）", 6, 10_000, 0.03, OFF, OFF),
        ("+ 指纹检测", 6, 10_000, 0.03, 2, OFF),
        ("+ 上下文裁剪 + 成本上限", 8, 10_000, 0.03, 2, 1500),
    ]

    # 第 4 行允许 8 步：前面 2 步查资料 + 4 步重复（被拦下后换路）+ 收尾
    # 裁剪的目标不是"少花 token"，而是"把预算留给真正有用的步"

    print(f"\n{'配置':<26}{'步数':>5}{'token':>10}{'成本':>9}  停止原因")
    print("-" * 78)
    for label, steps, tokens, cost, repeats, ctx_cap in variants:
        r = run(
            budget=Budget(max_steps=steps, max_tokens=tokens, max_cost=cost),
            guard=LoopGuard(max_repeats=repeats),
            limiter=ContextLimiter(max_tokens=ctx_cap),
            show_prompt_budget=ctx_cap != OFF,
        )
        print(f"{label:<26}{r['steps']:>5}{r['tokens']:>10,}{r['cost']:>9.4f}  {r['stop']}")

    print("\n怎么读这张表：每一行只比上一行多一道刹车，看差在哪。")
    print("\n四个设计取舍：")
    print("  · 检查放执行之前   → 越界的那次调用不会真的发生")
    print("  · 返回原因字符串   → 事后能分清「步数用完」和「钱用完」，处理方式不同")
    print("  · 指纹拦截不终止   → 给模型一次换路的机会，成功率更高")
    print("  · 剩余预算写进提示 → 让模型自己收敛，比硬拦更省（第 23 章细讲）")


if __name__ == "__main__":
    main()
