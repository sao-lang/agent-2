"""第 16 章 · 第 2 级：加第一道刹车 —— 预算。

运行：
    python code/ch16_loop/step2_budget.py

新增的一个概念：**执行之前检查预算**。

你会看到：只加这一个东西，步数就从 20 掉到 12，成本降了一个量级。
但代价是 —— 它"停下来了"，却没说清"为什么停"。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 粗略估算：中文约 0.7 token/字，英文约 0.25 token/词。够用来做对照实验。
PRICE_PER_1K_TOKENS = 0.002      # ¥ / 1K token，假设值


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


@dataclass
class Budget:
    """预算三件套。任一耗尽就必须停。"""

    max_steps: int = 12
    max_tokens: int = 60_000
    max_cost: float = 0.05

    steps_used: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0

    def spend(self, tokens: int) -> None:
        self.steps_used += 1
        self.tokens_used += tokens
        self.cost_used += tokens / 1000 * PRICE_PER_1K_TOKENS

    def exhausted(self) -> str | None:
        """返回 None 表示还有余量；返回字符串表示"因为什么停了"。"""
        if self.steps_used >= self.max_steps:
            return f"steps({self.max_steps})"
        if self.tokens_used >= self.max_tokens:
            return f"tokens({self.max_tokens})"
        if self.cost_used >= self.max_cost:
            return f"cost(¥{self.max_cost})"
        return None


@dataclass
class FakeBrain:
    """和 step1 完全一样的假模型 —— 对照实验只改一个变量。"""

    max_steps: int = 20
    step: int = 0
    seen: dict[str, int] = field(default_factory=dict)

    def think(self) -> dict:
        self.step += 1
        q = "上季度销量"
        self.seen[q] = self.seen.get(q, 0) + 1
        return {"tool": "search", "args": {"q": q}, "tokens": 150}


def run(budget: Budget) -> tuple[Budget, str]:
    brain = FakeBrain()
    while True:
        # ← 唯一的变化：先检查，再执行
        hit = budget.exhausted()
        if hit:
            return budget, hit
        action = brain.think()
        budget.spend(action["tokens"])
        if brain.step >= brain.max_steps:
            return budget, "model_says_done"


def main() -> None:
    print("=" * 66)
    print("第 2 级：执行之前检查预算")
    print("=" * 66)

    # 对照组：预算放到等于没有
    free = Budget(max_steps=10**9, max_tokens=10**9, max_cost=1e9)
    b0, why0 = run(free)

    # 实验组：正常预算
    b1, why1 = run(Budget(max_steps=12, max_tokens=60_000, max_cost=0.05))

    print(f"\n{'':<16}{'步数':>6}{'token':>10}{'成本':>10}  停止原因")
    print(f"{'无预算':<16}{b0.steps_used:>6}{b0.tokens_used:>10,}{b0.cost_used:>10.4f}  {why0}")
    print(f"{'有预算':<16}{b1.steps_used:>6}{b1.tokens_used:>10,}{b1.cost_used:>10.4f}  {why1}")

    saved = 1 - b1.tokens_used / b0.tokens_used
    print(f"\n→ token 减少 {saved:.0%}，成本从 ¥{b0.cost_used:.4f} 降到 ¥{b1.cost_used:.4f}")

    print("\n这一级解决了什么：循环一定会在有限步内停下来。")
    print("这一级没解决什么：它还是会用同一个参数重复 12 次。")
    print("\n👉 下一级：让「重复」这件事本身变成刹车。")


if __name__ == "__main__":
    main()
