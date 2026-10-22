"""第 16 章 · 第 1 级：最裸的 Agent 循环，没有任何刹车。

运行：
    python code/ch16_loop/step1_runaway.py

这一级只做一件事：让你亲眼看见"没人踩刹车"的循环会跑到哪里去。
它故意不设上限（上限写在 FakeBrain 里，代表模型自己"决定"要跑多久）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ledger:
    """账本：只记账，不拦截。"""

    calls: int = 0
    tokens: int = 0

    def spend(self, tokens: int) -> None:
        self.calls += 1
        self.tokens += tokens


@dataclass
class FakeBrain:
    """假模型：永远"还差一点"，永远想再搜一次。

    真实模型不会这么直白，但它"再试一次就好"的倾向是真的。
    """

    max_steps: int = 20          # 模型自己"觉得"要做多少步
    step: int = 0
    seen: dict[str, int] = field(default_factory=dict)

    def think(self) -> dict:
        self.step += 1
        q = "上季度销量"           # ← 注意：关键词一直不变
        self.seen[q] = self.seen.get(q, 0) + 1
        return {"tool": "search", "args": {"q": q}, "tokens": 150}


def main() -> None:
    brain = FakeBrain()
    ledger = Ledger()
    log: list[str] = []

    # 这就是全部：while 循环 + 调用工具，没有任何终止保障
    while True:
        action = brain.think()
        ledger.spend(action["tokens"])
        log.append(f"step {ledger.calls}: {action['tool']}({action['args']})")
        if brain.step >= brain.max_steps:
            break

    print("=" * 60)
    print("没有任何刹车的循环")
    print("=" * 60)
    for line in log[:4]:
        print("  " + line)
    print(f"  ...（中间省略 {len(log) - 8} 行）...")
    for line in log[-4:]:
        print("  " + line)

    print(f"\n总调用次数 : {ledger.calls}")
    print(f"累计 token : {ledger.tokens:,}")

    dup = max(brain.seen.values())
    print("\n问题清单：")
    print(f"  ① 跑了 {ledger.calls} 步才停 —— 停的原因是「模型自己不想跑了」，不是程序约束")
    print(f"  ② 同一个查询重复了 {dup} 次 —— 参数完全一样，结果必然一样")
    print("  ③ 没人知道花了多少钱 —— 账本只记了 token，没记钱")
    print("\n👉 这三件事，就是这一章要修的三个问题。")
    print("   （第四个问题「上下文越滚越大」在 step3 之后用实验展示）")


if __name__ == "__main__":
    main()
