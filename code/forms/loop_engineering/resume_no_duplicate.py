"""第 k 步杀进程后恢复：副作用不重复。

不联网。第 3 笔扣款成功之后、检查点写盘之前进程死掉，这是恢复语义最难的那一格：
动作已经发生，状态里没有记录。恢复后重放第 3 步，会不会扣第二次？

运行：python code/forms/loop_engineering/resume_no_duplicate.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from loop_core import Action, Limits, Loop

ORDERS = ["O1", "O2", "O3"]
AMOUNT = 199
TASK = "给 3 笔订单各扣 199 元"


class Killed(Exception):
    """模拟进程被杀：不给清理机会。"""


class Bank:
    """外部系统。幂等表在它这一侧，不在 agent 这一侧。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.keys: set[str] = set(json.loads(path.read_text("utf-8"))) if path.exists() else set()
        self.attempts = 0
        self.settled: list[str] = []

    def charge(self, order: str, key: str | None) -> str:
        self.attempts += 1
        if key is not None and key in self.keys:
            return f"{order} 幂等键命中，跳过（余额不变）"
        if key is not None:
            self.keys.add(key)
            self.path.write_text(json.dumps(sorted(self.keys)), encoding="utf-8")
        self.settled.append(order)
        return f"{order} 扣款 {AMOUNT} 元成功"


def save_checkpoint(path: Path, step: int, settled: list[str]) -> None:
    path.write_text(json.dumps({"step": step, "settled": settled}, ensure_ascii=False), encoding="utf-8")


def load_checkpoint(path: Path) -> dict:
    return json.loads(path.read_text("utf-8")) if path.exists() else {"step": 0, "settled": []}


def phase_one(bank: Bank, cp: Path) -> None:
    """前两步正常，第三步扣款成功后进程死掉，检查点还停在第 2 步。"""
    for i, order in enumerate(ORDERS):
        if i == 2:
            bank.charge(order, f"{order}:charge")
            raise Killed("进程在第 3 步扣款成功后被杀")
        bank.charge(order, f"{order}:charge")
        save_checkpoint(cp, i + 1, bank.settled)


def resume(bank: Bank, cp: Path, use_idem: bool, offset: int) -> Loop:
    state = load_checkpoint(cp)
    remaining = ORDERS[state["step"]:]

    def policy(lp: Loop, obs: str) -> Action | None:
        left = lp.state.get("left", [])
        if not left:
            return None
        return Action("charge", left[0])

    def act(lp: Loop, action: Action) -> str:
        lp.state["left"] = lp.state["left"][1:]
        key = f"{action.target}:charge" if use_idem else None
        return bank.charge(action.target, key)

    lp = Loop(f"resume-{int(use_idem)}", policy, act, Limits(max_steps=6))
    lp.state["left"] = remaining
    lp.steps = offset                      # 轨迹的 step 从断点继续，不重新从 1 数
    lp.result = lp.run(f"{TASK}（从第 {offset + 1} 步恢复）")
    return lp


def scenario(use_idem: bool) -> None:
    tmp = Path(__file__).with_name("_work_resume")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    bank = Bank(tmp / "idem.json")
    cp = tmp / "checkpoint.json"
    label = "有幂等键" if use_idem else "无幂等键"
    print(f"=== {label} ===")
    try:
        phase_one(bank, cp)
    except Killed as e:
        print(f"    第一次运行：{e}")
    print(f"    检查点内容：{cp.read_text('utf-8')}")
    print(f"    崩溃前外部系统已结算：{bank.settled}（{len(bank.settled)} 笔）")

    offset = load_checkpoint(cp)["step"]
    lp = resume(bank, cp, use_idem, offset)
    print(f"    恢复后终止={lp.result.reason} 从第 {offset + 1} 步继续，共走 {lp.steps - offset} 步")
    for row in lp.records:
        print(f"      step={row['step']} {row['action']:<12} {row['verdict']}")
    print(f"    外部系统被请求 {bank.attempts} 次，实际结算 {len(bank.settled)} 笔：{bank.settled}")
    print(f"    结论：{label}，恢复共扣 {len(bank.settled)} 次，重复 {len(bank.settled) - len(ORDERS)} 笔")
    print()


def main() -> None:
    print("=== 场景：3 笔扣款，第 3 笔成功后进程被杀，检查点停在第 2 步 ===")
    print()
    scenario(use_idem=False)
    scenario(use_idem=True)
    print("=== 要点 ===")
    print("    1 检查点记的是'做到第几步'，不是'动作发生了没有'")
    print("    2 动作成功与检查点写盘之间一定有一个窗口，恢复必然重放这一步")
    print("    3 幂等键必须由执行动作的那一侧保存，agent 恢复后自己记的账不作数")
    shutil.rmtree(Path(__file__).with_name("_work_resume"), ignore_errors=True)


if __name__ == "__main__":
    main()

