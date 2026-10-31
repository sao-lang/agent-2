"""开 / 关 verify 的对照：同一个任务，同一份脚本化策略，只换完成判定。

不联网。策略是固定剧本（候选补丁按顺序试），正确候选由 seed 决定，
因此这张表是结构对照，不是模型实测成功率。

关掉 verify 时没有人跑测试：完成由策略自述判定，代价是"错的补丁被当成完成交出去"。
打开 verify 时每试一个补丁就跑一次测试：完成由退出码判定。

运行：python code/forms/loop_engineering/verify_toggle.py
"""

from __future__ import annotations

import random

from loop_core import Action, Hooks, Limits, Loop, Verdict

CANDIDATES = ["补丁A：改 total 的初始值", "补丁B：改循环上界", "补丁C：改返回语句"]
TASK = "把 calc.py 改到 3 个测试全绿"


def make_policy(declare_after_first: bool):
    def policy(lp: Loop, obs: str) -> Action | None:
        tried = lp.state.setdefault("tried", [])
        if declare_after_first and tried:
            return None                       # 模型自述"改完了"
        if lp.last_result.startswith("测试通过"):
            return None                       # 裁判说绿了，才敢停
        if len(tried) >= len(CANDIDATES):
            return None                       # 候选用完
        return Action("patch", CANDIDATES[len(tried)])
    return policy


def make_act(correct: int, run_tests: bool):
    def act(lp: Loop, action: Action) -> str:
        idx = CANDIDATES.index(action.target)
        lp.state["tried"] = lp.state.get("tried", []) + [action.target]
        if not run_tests:
            lp.state["green"] = None
            lp.state["last_tried"] = idx
            return f"已把 {action.target} 写入 calc.py（未运行测试）"
        lp.state["last_tried"] = idx
        if idx == correct:
            lp.state["green"] = True
            return "测试通过：3 passed in 0.02s"
        lp.state["green"] = False
        return f"测试失败：{action.target} 之后 test_total 期望 12 实际 10（1 failed）"
    return act


def make_hooks(use_verify: bool) -> Hooks:
    hooks = Hooks()
    if use_verify:
        hooks.verify = lambda lp, a, result: Verdict(
            result.startswith("测试通过"),
            "tests green" if result.startswith("测试通过") else "1 failed",
        )
    return hooks


def run_one(seed: int, use_verify: bool) -> Loop:
    correct = random.Random(seed).randrange(len(CANDIDATES))
    lp = Loop(f"verify-{int(use_verify)}-{seed}",
              make_policy(declare_after_first=not use_verify),
              make_act(correct, run_tests=use_verify),
              Limits(max_steps=6), make_hooks(use_verify))
    lp.run(TASK)
    lp.state["correct"] = correct
    return lp


def is_correct(lp: Loop) -> bool:
    """外部口径的成功：最后交出去的那个补丁是不是正确的那一个。"""
    return lp.state.get("last_tried") == lp.state.get("correct")


def report(label: str, use_verify: bool, n: int = 30) -> None:
    wins = steps = tokens = 0
    for seed in range(n):
        lp = run_one(seed, use_verify)
        wins += int(is_correct(lp))
        steps += lp.steps
        tokens += lp.tokens
    per_success = tokens / wins if wins else float("inf")
    print(f"  {label:<12} 成功 {wins:>2}/{n}  平均步数 {steps / n:.2f}  "
          f"总 tokens {tokens:>6}  每成功一次 {per_success:7.0f} tokens")


def print_trace(lp: Loop, title: str) -> None:
    print(title)
    print(f"    正确候选={CANDIDATES[lp.state['correct']]}  "
          f"最后交出的候选={CANDIDATES[lp.state.get('last_tried', -1)]}  "
          f"外部判定={'通过' if is_correct(lp) else '不通过'}")
    for row in lp.records:
        print(f"    step={row['step']} {row['phase']:<6} {row['action']:<22} "
              f"verdict={row['verdict']:<10} obs={row['observation_hash']}")


def main() -> None:
    print("=== 1. 同一任务，只差一个 verify 插点（30 个 seed） ===")
    report("关掉 verify", use_verify=False)
    report("打开 verify", use_verify=True)

    print()
    print("=== 2. 一次关掉 verify 的运行（正确候选是 B，交出去的是 A） ===")
    lp_off = run_one(seed=0, use_verify=False)
    print_trace(lp_off, "")

    print()
    print("=== 3. 同一次任务打开 verify 的运行 ===")
    lp_on = run_one(seed=0, use_verify=True)
    print_trace(lp_on, "")

    print()
    print("=== 4. 两种口径的账 ===")
    print("    关掉 verify：单次最便宜，但每成功一次要为 3 次里的 2 次白跑付账")
    print("    打开 verify：单次变贵，几乎不再把失败当完成交出去")


if __name__ == "__main__":
    main()

