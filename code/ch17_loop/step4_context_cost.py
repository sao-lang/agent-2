"""第 17 章 · 第 4 级：加第三、四道刹车 —— 上下文裁剪 + 成本上限。

运行：
    python code/ch17_loop/step4_context_cost.py

新增的两个概念：
  ③ 上下文裁剪（含单条消息截断）—— 治"越跑越贵"
  ④ 成本硬上限                —— 治"单步极贵"

这一级的关键发现（也是最容易做错的地方）：
  裁剪的价值不是"省总 token"，而是"同样的预算能撑更多步"。
  用总 token 去评价裁剪，会得出"没用"的错误结论。
"""
from __future__ import annotations

from dataclasses import dataclass

PRICE_PER_1K_TOKENS = 0.002


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


def truncate_tokens(text: str, max_tokens: int) -> str:
    """截断时保留头尾。工具返回的结论、错误信息通常在末尾。"""
    t = est_tokens(text)
    if t <= max_tokens:
        return text
    keep = int(len(text) * max_tokens / t)
    head = keep // 2
    return f"{text[:head]}\n...<省略 {t - max_tokens} token>...\n{text[-(keep - head):]}"


@dataclass
class ContextLimiter:
    """两层裁剪：先削单条，再削总量。

    只做"少留几条"是不够的 —— 一条工具结果就能有 2000 token。
    """

    max_tokens: int = 4000
    per_message_cap: int = 800

    def trim(self, messages: list[str]) -> list[str]:
        kept: list[str] = []
        total = 0
        for m in reversed(messages):
            m = truncate_tokens(m, self.per_message_cap)
            t = est_tokens(m)
            if total + t > self.max_tokens:
                break
            kept.append(m)
            total += t
        return list(reversed(kept))


@dataclass
class Budget:
    max_steps: int = 30
    max_tokens: int = 10**9
    max_cost: float = 10.0
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


def run(mode: str, *, limiter: ContextLimiter | None, budget: Budget) -> dict:
    """mode='context'：每轮工具都吐一大坨；mode='expensive'：每步长输出。"""
    history: list[str] = ["用户：帮我看看上季度销量"]

    while True:
        hit = budget.exhausted()
        if hit:
            return {"steps": budget.steps_used, "tokens": budget.tokens_used,
                    "cost": budget.cost_used, "stop": hit}

        ctx = limiter.trim(history) if limiter else history
        input_tokens = sum(est_tokens(m) for m in ctx)

        if mode == "context":
            output, obs = "继续", "检索结果：" + "内容" * 1500
        else:
            output, obs = "分析：" + "细节" * 2000, ""

        budget.spend(input_tokens, est_tokens(output))
        history.append(output)
        if obs:
            history.append(obs)


def main() -> None:
    print("=" * 74)
    print("第 4 级：上下文裁剪 + 成本上限")
    print("=" * 74)

    # 两组共用同一个成本上限：只有"裁剪"这一个变量在变
    rows: dict[str, dict[str, dict]] = {}
    print(f"\n{'场景':<14}{'裁剪':<6}{'步数':>5}{'token':>9}{'成本':>9}  停止原因")
    print("-" * 74)
    for label, mode in (("③ 上下文爆炸", "context"), ("④ 成本击穿", "expensive")):
        rows[label] = {}
        for name, lim in (("关", ContextLimiter(max_tokens=10**9)),
                          ("开", ContextLimiter(max_tokens=4000))):
            r = run(mode, limiter=lim, budget=Budget(max_steps=30, max_cost=0.05))
            rows[label][name] = r
            print(f"{label:<14}{name:<6}{r['steps']:>5}{r['tokens']:>9,}{r['cost']:>9.4f}  {r['stop']}")

    print("\n★ ③ 这一组要仔细看：裁剪后 token 只少了一点，但步数多了。")
    for name in ("关", "开"):
        r = rows["③ 上下文爆炸"][name]
        print(f"   裁剪{name} : {r['steps']:>2} 步 / {r['tokens']:,} token "
              f"→ 每 1,000 token 换来 {r['steps'] / r['tokens'] * 1000:.2f} 步")
    print("   → 正确的评价口径是「单位 token 完成多少工作」，不是「总 token 少了多少」。")
    print("     用总 token 评价裁剪，会得出「裁剪没用」的错误结论。")

    print("\n★ ④ 这一组：单步 8000 token 的贵模型，只有成本上限拦得住。")
    print("   步数限制对它几乎无效 —— 几步就把钱花完了。")


if __name__ == "__main__":
    main()
