"""第 16 章 · 第 3 级：加第二道刹车 —— 重复调用检测（指纹）。

运行：
    python code/ch16_loop/step3_duplicate.py

新增的一个概念：**给每次工具调用算一个指纹，重复超过 N 次就拦。**

这一级是全书性价比最高的一段代码：15 行，省 90%。
但"直接终止"不是最优解 —— 更好的做法是告诉模型"别再试了"，给它换路的机会。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

PRICE_PER_1K_TOKENS = 0.002


@dataclass
class Budget:
    max_steps: int = 12
    steps_used: int = 0
    tokens_used: int = 0

    def spend(self, tokens: int) -> None:
        self.steps_used += 1
        self.tokens_used += tokens

    def exhausted(self) -> str | None:
        return f"steps({self.max_steps})" if self.steps_used >= self.max_steps else None


@dataclass
class LoopGuard:
    """重复调用检测。

    指纹 = 工具名 + 排好序的参数。排序是关键：
    {"q": "x", "n": 5} 和 {"n": 5, "q": "x"} 是同一个调用，
    不排序就会算成两个不同指纹，检测直接失效。
    """

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
class FakeBrain:
    """同一个"想再搜一次"的模型。"""

    max_steps: int = 20
    step: int = 0

    def think(self) -> dict:
        self.step += 1
        return {"tool": "search", "args": {"q": "上季度销量"}, "tokens": 150}


def run(guard: LoopGuard | None) -> dict:
    brain, budget = FakeBrain(), Budget(max_steps=12, steps_used=0)

    while True:
        hit = budget.exhausted()
        if hit:
            return {"steps": budget.steps_used, "tokens": budget.tokens_used, "stop": hit, "repeats": 0}

        action = brain.think()
        if guard:
            why = guard.check(action["tool"], action["args"])
            if why:
                return {
                    "steps": budget.steps_used,
                    "tokens": budget.tokens_used,
                    "stop": f"guard:{why[:24]}",
                    "repeats": max(guard._seen.values()),
                }
        budget.spend(action["tokens"])
        if brain.step >= brain.max_steps:
            return {"steps": budget.steps_used, "tokens": budget.tokens_used, "stop": "model_done", "repeats": 0}


def main() -> None:
    print("=" * 70)
    print("第 3 级：重复调用检测")
    print("=" * 70)

    no_guard = run(None)
    with_guard = run(LoopGuard(max_repeats=2))

    print(f"\n{'':<14}{'步数':>6}{'token':>9}{'成本':>9}  停止原因")
    for label, r in (("无指纹检测", no_guard), ("有指纹检测", with_guard)):
        cost = r["tokens"] / 1000 * PRICE_PER_1K_TOKENS
        print(f"{label:<14}{r['steps']:>6}{r['tokens']:>9,}{cost:>9.4f}  {r['stop']}")

    base = no_guard["tokens"] / 1000 * PRICE_PER_1K_TOKENS
    now = with_guard["tokens"] / 1000 * PRICE_PER_1K_TOKENS
    print(f"\n→ 成本 ¥{base:.4f} → ¥{now:.4f}（减少 {1 - now / base:.0%}）")

    # 演示 sort_keys 的作用
    print("\n为什么指纹必须对参数排序：")
    a = LoopGuard.fingerprint("search", {"q": "x", "n": 5})
    b = LoopGuard.fingerprint("search", {"n": 5, "q": "x"})
    print(f"  sort_keys=True  : {a} == {b} → {a == b}  ← 正确")
    raw_a = hashlib.md5(json.dumps({"tool": "search", "args": {"q": "x", "n": 5}}).encode()).hexdigest()[:12]
    raw_b = hashlib.md5(json.dumps({"tool": "search", "args": {"n": 5, "q": "x"}}).encode()).hexdigest()[:12]
    print(f"  sort_keys=False : {raw_a} == {raw_b} → {raw_a == raw_b}  ← 漏拦")

    print("\n这一级解决了什么：参数完全相同的重复调用被拦住。")
    print("这一级没解决什么：参数稍改一个字（'销量'→'季度销量'）就绕过去了，")
    print("                  而且工具返回的内容会一路堆进上下文 —— 越跑越贵。")


if __name__ == "__main__":
    main()
