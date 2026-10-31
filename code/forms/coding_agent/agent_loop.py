"""编码 agent 的最小闭环：六步修一个真 bug，中间有一次修错方向。

不联网。真仓库（repo_fixture 生成）、真工具（tools.Repo）、真测试（子进程跑）。
策略是固定剧本；唯一的分支是"测试红了就换假设"，这个分支由 run 的退出码触发。

三种剧本，由 seed 决定用哪一种：
  0 第一次假设就对               4 步
  1 第一次修错方向，第二次改对    6 步
  2 两次都假设错，停止并交给人    6 步（失败）

运行：python code/forms/coding_agent/agent_loop.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

import repo_fixture
from tools import Repo

BUGGY = """def average(values):
    return total(values) / (len(values) - 1)"""
ROUNDED = """def average(values):
    return round(total(values) / (len(values) - 1), 2)"""
GUARDED = """def average(values):
    if not values:
        return 0.0
    return total(values) / (len(values) - 1)"""
FIXED = """def average(values):
    if not values:
        return 0.0
    return total(values) / len(values)"""


@dataclass
class Step:
    n: int
    tool: str
    arg: str
    result: str
    tokens: int


@dataclass
class Run:
    mode: int
    steps: list[Step] = field(default_factory=list)
    tokens: int = 0
    green: bool = False
    hidden_green: bool = False
    gave_up: bool = False

    def add(self, tool: str, arg: str, result) -> None:
        self.tokens += getattr(result, "tokens", 0)
        self.steps.append(Step(len(self.steps) + 1, tool, arg, str(result), self.tokens))


def run_once(seed: int = 0, mode: int | None = None) -> Run:
    if mode is None:
        mode = (0, 1, 1, 2)[seed % 4]
    repo = Repo(repo_fixture.ensure())
    run = Run(mode)

    run.add("list_tree", ".", repo.list_tree())
    run.add("read_file", "src/calc.py", repo.read_file("src/calc.py"))

    if mode == 0:
        run.add("apply_patch", "src/calc.py", repo.apply_patch("src/calc.py", BUGGY, FIXED))
    elif mode == 1:
        run.add("apply_patch", "src/calc.py", repo.apply_patch("src/calc.py", BUGGY, ROUNDED))
        run.add("run", "tests/test_calc.py", repo.run("python tests/test_calc.py"))
        run.add("apply_patch", "src/calc.py", repo.apply_patch("src/calc.py", ROUNDED, FIXED))
    else:
        run.add("apply_patch", "src/calc.py", repo.apply_patch("src/calc.py", BUGGY, ROUNDED))
        run.add("run", "tests/test_calc.py", repo.run("python tests/test_calc.py"))
        run.add("apply_patch", "src/calc.py", repo.apply_patch("src/calc.py", ROUNDED, GUARDED))
        run.add("run", "tests/test_calc.py", repo.run("python tests/test_calc.py"))
        run.gave_up = True

    if not run.gave_up:
        final = repo.run("python tests/test_calc.py")
        run.add("run", "tests/test_calc.py", final)
        run.green = "exit=0" in str(final)
    hidden = repo.run("python tests/hidden_test_calc.py")
    run.hidden_green = "exit=0" in str(hidden)
    if run.gave_up:
        run.green = "exit=0" in str(run.steps[-1].result)
    return run


def show(run: Run) -> None:
    print(f"    {'步':<3}{'工具':<13}{'参数':<18}{'累计tokens':>10}  结果首行")
    for s in run.steps:
        first = s.result.splitlines()[0][:44]
        print(f"    {s.n:<3}{s.tool:<13}{s.arg:<18}{s.tokens:>10}  {first}")


def main() -> None:
    print("=== 1. 六步修 bug 的完整轨迹（第一次补丁修错方向） ===")
    run = run_once(mode=1)
    show(run)
    print(f"    可见测试={'绿' if run.green else '红'}  隐藏测试={'绿' if run.hidden_green else '红'}  "
          f"tokens={run.tokens}")

    print()
    print("=== 2. 第 3、4 步的完整输出（错在哪、测试怎么把它拉回来） ===")
    for s in run.steps[2:4]:
        print(f"    [{s.n}] {s.tool} {s.arg}")
        for line in s.result.splitlines():
            print(f"        {line}")

    print()
    print("=== 3. 最后一次运行的完整输出 ===")
    for line in run.steps[-1].result.splitlines():
        print(f"    {line}")

    print()
    print("=== 4. 两次假设都错时它停下来（不是继续瞎改） ===")
    bad = run_once(mode=2)
    show(bad)
    print(f"    可见测试={'绿' if bad.green else '红'}  隐藏测试={'绿' if bad.hidden_green else '红'}  "
          f"停止=放弃（假设用完）")


if __name__ == "__main__":
    main()
