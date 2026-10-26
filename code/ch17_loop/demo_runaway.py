"""第 17 章示例：分别制造四种失控，然后加刹车修好它。

运行：
    python code/ch17_loop/demo_runaway.py

不需要 API key：用 FakeBrain 模拟模型行为，重点是可复现地观察"失控形态"。

对照实验的公平性：每组只改**一个**变量，其他全部相同。
这是第 38 章"一次只改一个变量"的第一次实践。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.guards import Budget, ContextLimiter, LoopGuard, StepResult, run_loop  # noqa: E402


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


MAX_STEPS = 20
FREE = 10**9  # 对照组：把某道刹车放到"等于没有"


# ---------------------------------------------------------------- 假模型

class FakeBrain:
    """通过 mode 控制它怎么"想"，用来复现四种失败形态。"""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.n = 0

    def __call__(self, messages: list[dict], step: int) -> StepResult:
        self.n += 1

        if self.mode == "runaway":
            # 永远在搜索，永远不结束
            return StepResult(
                done=False,
                output="继续搜索关键词",
                tool_calls=[{"tool": "search", "args": {"q": f"关键词{self.n}"}}],
                tokens=50,
                cost=0.0005,
                reason="search",
            )

        if self.mode == "thrash":
            # 参数一模一样，反复调用
            return StepResult(
                done=False,
                output="再查一次",
                tool_calls=[{"tool": "search", "args": {"q": "上季度销量"}}],
                tokens=50,
                cost=0.0005,
                reason="search(same)",
            )

        if self.mode == "context":
            # 每轮工具都返回一大坨数据（真实系统里"一次查回 200 条记录"就是这样）
            return StepResult(
                done=False,
                output="继续" if step else "需要更多信息。" * 400,
                tool_calls=[{"tool": "fetch", "args": {"url": f"https://x/{self.n}"}}],
                tokens=40 if step else 2000,
                cost=0.001,
                reason="fetch",
                observation="检索结果：" + "内容" * 1500,
            )

        if self.mode == "expensive":
            # 贵模型 + 超长输出：每一步都很贵
            return StepResult(
                done=False,
                output="分析：" + "细节" * 2000,
                tool_calls=[],
                tokens=8000,
                cost=0.02,
                reason="deep-think",
            )

        # 正常：两步就结束
        if step == 0:
            return StepResult(
                done=False,
                output="先查一下",
                tool_calls=[{"tool": "search", "args": {"q": "销量"}}],
                tokens=120,
                cost=0.0001,
                reason="search",
            )
        return StepResult(done=True, output="搞定", tokens=80, cost=0.0001, reason="finish")


def act(tool: str, args: dict) -> str:
    return f"{tool} 返回 3 条结果"


def run_case(name: str, mode: str, brake: bool) -> dict:
    print(f"\n{'=' * 62}\n{name}\n{'=' * 62}")
    return run_loop(
        think=FakeBrain(mode),
        act=act,
        # 只放开被测的那道刹车，其余全部收紧 —— 否则测的就不是这个变量
        budget=Budget(
            max_steps=FREE if (mode == "runaway" and not brake) else MAX_STEPS,
            max_tokens=FREE if (mode == "context" and not brake) else 60_000,
            max_cost=FREE if (mode == "expensive" and not brake) else 0.05,
        ),
        guard=LoopGuard(max_repeats=2) if (brake or mode == "context") else LoopGuard(max_repeats=10**9),
        limiter=ContextLimiter(max_tokens=4000) if brake else ContextLimiter(max_tokens=10**9),
        est_tokens=est_tokens,
        truncate="on" if brake else None,
    )


def main() -> None:
    cases = [
        ("① 无限循环：无预算", "runaway", False),
        ("① 无限循环：step/token/cost 三重预算", "runaway", True),
        ("② 重复调用：无指纹检测", "thrash", False),
        ("② 重复调用：加指纹检测", "thrash", True),
        ("③ 上下文爆炸：不裁剪", "context", False),
        ("③ 上下文爆炸：裁剪到 4000 token", "context", True),
        ("④ 成本击穿：无预算", "expensive", False),
        ("④ 成本击穿：加预算", "expensive", True),
    ]
    rows = []
    for name, mode, brake in cases:
        r = run_case(name, mode, brake)
        rows.append((name, r))
        print(
            f"\n→ 停止原因: {r['stop_reason']}\n"
            f"   步数: {r['steps']}  累计 token: {r['tokens']:,}  成本: ¥{r['cost']:.4f}"
        )

    print(f"\n{'=' * 62}\n汇总\n{'=' * 62}")
    print(f"{'case':<34}{'steps':>6}{'tokens':>10}{'cost':>10}  stop")
    for name, r in rows:
        print(f"{name:<34}{r['steps']:>6}{r['tokens']:>10,}{r['cost']:>10.4f}  {r['stop_reason'][:26]}")


if __name__ == "__main__":
    main()
