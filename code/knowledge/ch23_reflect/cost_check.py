"""带反思的循环贵多少：无裁判 / 自评 / 外部裁判三档的调用数与通过率。

原理演示：生成器、裁判与修复器都是脚本化的，数字由本脚本自己算出，
不是某个模型的实测。三档共用同一批任务与同一个生成器，差别只在
"谁来判、判完修不修、修几轮"。
"""

from __future__ import annotations

import random

TASKS = 20
ROUNDS = 4
REPAIR_P = 0.55        # 定向重生成一次就改对的概率
MIN_GAIN = 2           # 一轮至少要多通过 2 个任务，才认为收益不是样本噪声


# ---------------------------------------------------------------- 任务与真值

def make_tasks(n: int = TASKS, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    tasks = []
    for i in range(n):
        signed = rng.choice([3, 10, 30])
        tasks.append({
            "id": f"A{1000 + i}",
            "signed_days_ago": signed,
            "window_days": 7,
            "expect_over": signed > 7,
        })
    return tasks


def truth(artifact: dict, task: dict) -> bool:
    """测量用真值：只用来统计通过率，不参与任何一轮的判定。"""
    if artifact["days"] != task["signed_days_ago"]:
        return False
    says_over = "超过" in artifact["reason"]
    if says_over != (artifact["days"] > task["window_days"]):
        return False
    return says_over == task["expect_over"]


# ---------------------------------------------------------------- 生成与裁判

def generate(task: dict, rng: random.Random) -> dict:
    """生成器：天数抄对的概率 0.9，结论说反的概率 0.3（与天数抄错无关）。"""
    days = task["signed_days_ago"] if rng.random() < 0.9 else rng.choice([3, 10, 30])
    says_over = (not task["expect_over"]) if rng.random() < 0.3 else task["expect_over"]
    reason = "超过 7 天窗口" if says_over else "7 天内，可退"
    return {"order_id": task["id"], "days": days, "reason": reason}


def self_review(_artifact: dict) -> tuple[bool, str]:
    """自评：输入只有产物，没有事实，脚本化后就是"总是通过"。"""
    return True, "看起来合理，字段齐全。"


def external_judge(artifact: dict, task: dict) -> list[str]:
    """外部裁判：规则（字段与事实一致）+ 测试（结论与期望一致）。"""
    out: list[str] = []
    if artifact["days"] != task["signed_days_ago"]:
        out.append("days 与事实不符")
    says_over = "超过" in artifact["reason"]
    if says_over != (artifact["days"] > task["window_days"]):
        out.append("结论与 days 矛盾")
    if says_over != task["expect_over"]:
        out.append("结论与政策不符")
    return out


def repair(artifact: dict, task: dict, problems: list[str],
           rng: random.Random) -> dict:
    """修复：能由事实直接确定的字段零调用改掉，措辞走一次定向重生成。"""
    out = dict(artifact)
    if "days 与事实不符" in problems:
        out["days"] = task["signed_days_ago"]
    if rng.random() < REPAIR_P:
        over = out["days"] > task["window_days"]
        out["reason"] = "超过 7 天窗口" if over else "7 天内，可退"
    return out


# ---------------------------------------------------------------- 三档

def run_no_judge(tasks: list[dict], rng: random.Random) -> dict:
    calls = 0
    passed = 0
    for task in tasks:
        artifact = generate(task, rng)
        calls += 1
        passed += truth(artifact, task)
    return {"name": "无裁判", "calls": calls, "passed": passed, "rounds": []}


def run_self_judge(tasks: list[dict], rng: random.Random, rounds: int = 2) -> dict:
    """自评两轮：每轮一次"检查"、一次"改进"，检查恒通过，改进按 0.5 改写措辞。"""
    calls = 0
    passed = 0
    for task in tasks:
        artifact = generate(task, rng)
        calls += 1
        for _ in range(rounds):
            self_review(artifact)
            calls += 1
            artifact = repair(artifact, task, [], rng) if rng.random() < 0.5 else artifact
            calls += 1
        passed += truth(artifact, task)
    return {"name": f"自评 {rounds} 轮", "calls": calls, "passed": passed, "rounds": []}


def run_external_judge(tasks: list[dict], rng: random.Random,
                       rounds: int = ROUNDS) -> dict:
    calls = len(tasks)                          # 每个任务先有一次生成
    judge_calls = 0
    repair_calls = 0
    passed = 0
    per_round: list[tuple[int, int, int]] = []   # (轮次, 本轮调用, 累计通过)
    alive = list(tasks)
    for r in range(1, rounds + 1):
        round_calls = 0
        still: list[dict] = []
        for task in alive:
            artifact = task["_artifact"]
            problems = external_judge(artifact, task)
            round_calls += 1
            judge_calls += 1
            if problems:
                round_calls += 1
                repair_calls += 1
                task["_artifact"] = repair(artifact, task, problems, rng)
                still.append(task)
        calls += round_calls
        passed = sum(truth(t["_artifact"], t) for t in tasks)
        per_round.append((r, round_calls, passed))
        alive = still
    return {"name": f"外部裁判 {rounds} 轮", "calls": calls, "passed": passed,
            "rounds": per_round, "judge": judge_calls, "repair": repair_calls}


def first_round_cost(tasks: list[dict], rng: random.Random) -> tuple[dict, int]:
    """外部裁判第 1 轮之前的生成调用。"""
    for task in tasks:
        task["_artifact"] = generate(task, rng)
    passed = sum(truth(t["_artifact"], t) for t in tasks)
    return {"name": "生成", "calls": len(tasks), "passed": passed, "rounds": []}, len(tasks)


# ---------------------------------------------------------------- 输出

def main() -> None:
    rng = random.Random(11)
    tasks = make_tasks()
    base, base_calls = first_round_cost(tasks, rng)

    no_judge = run_no_judge(tasks, random.Random(11))
    self_judge = run_self_judge(tasks, random.Random(11))
    ext = run_external_judge(tasks, random.Random(11))

    print(f"=== 三档：{TASKS} 个任务，同一个生成器 ===")
    print(f"{'档位':<14}{'总调用':>8}{'每任务':>9}{'通过':>7}{'通过率':>9}")
    for row in (no_judge, self_judge, ext):
        rate = row["passed"] / TASKS
        print(f"{row['name']:<14}{row['calls']:>8}{row['calls'] / TASKS:>9.2f}"
              f"{row['passed']:>7}{rate:>9.0%}")

    print()
    print("=== 外部裁判：逐轮边际（含每个任务的 1 次生成） ===")
    print(f"{'轮次':<6}{'本轮调用':>9}{'累计调用':>9}{'新增通过':>9}"
          f"{'累计通过':>9}{'调用/多通过1个':>15}")
    prev_passed = base["passed"]
    total = len(tasks)
    stop_at = None
    EXT_GAINS = []
    EXT_TOTALS: list[int] = []
    EXT_PASSED: list[int] = []
    for r, round_calls, passed in ext["rounds"]:
        total += round_calls
        gain = passed - prev_passed
        EXT_GAINS.append(gain)
        EXT_TOTALS.append(total)
        EXT_PASSED.append(passed)
        per_pass = f"{round_calls / gain:.1f}" if gain else "-"
        print(f"{r:<6}{round_calls:>9}{total:>9}{gain:>9}{passed:>9}{per_pass:>15}")
        if stop_at is None and gain < MIN_GAIN:
            stop_at = r
        prev_passed = passed

    print()
    if stop_at is None:
        print(f"停在第 {len(ext['rounds'])} 轮：每一轮新增通过都不低于 {MIN_GAIN} 个")
    else:
        idx = stop_at - 2
        print(f"修到第 {stop_at - 1} 轮为止：第 {stop_at} 轮只新增通过 "
              f"{EXT_GAINS[stop_at - 1]} 个，不足 {MIN_GAIN} 个，"
              f"收益落进 {TASKS} 个样本的噪声里")
        print(f"按这个判据停：{EXT_TOTALS[idx]} 次调用，通过 {EXT_PASSED[idx]}/{TASKS}，"
              f"每通过 1 个任务 {EXT_TOTALS[idx] / EXT_PASSED[idx]:.2f} 次调用")

    print()
    print("=== 同样通过率下的调用数 ===")
    for row in (no_judge, self_judge, ext):
        rate = row["passed"] / TASKS
        if rate <= 0:
            continue
        print(f"{row['name']:<14}通过率 {rate:>4.0%}  每通过 1 个任务 {row['calls'] / row['passed']:>5.2f} 次调用")

    print()
    print("=== 每任务调用拆开 ===")
    print(f"无裁判       生成 {no_judge['calls'] / TASKS:.2f}")
    print(f"自评 2 轮    生成 1.00 + 检查 {(self_judge['calls'] - TASKS) / 2 / TASKS:.2f}"
          f" + 改进 {(self_judge['calls'] - TASKS) / 2 / TASKS:.2f}")
    print(f"外部裁判     生成 1.00 + 判定 {ext['judge'] / TASKS:.2f}"
          f" + 修复 {ext['repair'] / TASKS:.2f}"
          f"（裁判与修复占 {(ext['calls'] - TASKS) / ext['calls']:.0%}）")


if __name__ == "__main__":
    main()
