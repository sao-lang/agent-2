"""第 9 章 · 第 2 级：把状态存进文件，真的跨进程续跑。

运行：
    python code/ch09_durable/step2_file_checkpoint.py save
    python code/ch09_durable/step2_file_checkpoint.py resume

新增的一个概念：**检查点（checkpoint）= 某一步执行完之后的状态快照。**

两个动作分开两次进程跑，才有意义：
  `save`   跑两步，把状态写进 JSON，然后进程退出
  `resume` 新进程启动，从 JSON 读回状态，跑完剩下的

如果你在同一个脚本里连续做这两件事，你只证明了"变量还在"，
没证明"进程重启后还能恢复"。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parents[2] / ".traces" / "ch09_step2_state.json"


@dataclass
class TaskState:
    goal: str
    plan: list[str] = field(default_factory=list)
    cursor: int = 0
    findings: list[str] = field(default_factory=list)


def save(state: TaskState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")


def load() -> TaskState:
    return TaskState(**json.loads(STATE_FILE.read_text(encoding="utf-8")))


def run_steps(state: TaskState, n: int) -> None:
    for _ in range(n):
        if state.cursor >= len(state.plan):
            break
        step = state.plan[state.cursor]
        state.findings.append(f"[完成] {step}")
        state.cursor += 1
    save(state)


def make_plan(goal: str) -> list[str]:
    return [f"检索：{goal}", "整理要点", "撰写结论"]


def cmd_save() -> None:
    state = TaskState(goal="调研竞品定价")
    state.plan = make_plan(state.goal)
    print("=== 第一次进程 ===")
    print(f"  计划：{state.plan}")
    run_steps(state, 2)          # 只跑两步，然后"崩溃"
    print(f"  跑完 2 步后：cursor={state.cursor}")
    print(f"  findings={state.findings}")
    print(f"\n  已写入：{STATE_FILE}")
    print("  现在进程退出（内存全部销毁）。")
    print("  下一步：python code/ch09_durable/step2_file_checkpoint.py resume")


def cmd_resume() -> None:
    if not STATE_FILE.exists():
        print("❌ 没有找到状态文件，请先运行 save")
        return
    state = load()
    print("=== 第二次进程（全新进程）===")
    print(f"  从文件恢复：goal={state.goal}")
    print(f"  cursor={state.cursor}  findings={state.findings}")
    print(f"  剩余步骤：{state.plan[state.cursor:]}")

    run_steps(state, 99)
    print(f"\n  跑完：cursor={state.cursor}")
    print(f"  findings={state.findings}")
    print("\n👉 关键点：前两步的结果是从磁盘读回来的，不是重新算的。")
    print("   这就是「断点续跑」的全部秘密：**状态能序列化 + 知道自己走到哪**。")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "save"
    {"save": cmd_save, "resume": cmd_resume}[cmd]()


if __name__ == "__main__":
    main()
