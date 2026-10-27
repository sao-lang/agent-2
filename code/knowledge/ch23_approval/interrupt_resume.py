"""中断与恢复：关掉页面，两小时后再回来，从哪一步继续。

不联网。检查点真的写在文件里，恢复真的从文件读；下游服务（发邮件）用幂等键
去重。三种恢复方式各跑一遍，比较每个副作用被执行了几次。
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

WORK = Path("_resume_demo").resolve()


@dataclass
class Step:
    idx: int
    name: str
    effect: str | None = None      # 有副作用时给一个幂等键


STEPS = [
    Step(1, "读政策文档"),
    Step(2, "算新期限"),
    Step(3, "给客户发确认邮件", "email:A1001"),
    Step(4, "写 policy.md", "file:policy.md"),
    Step(5, "发完成通知", "notify:A1001"),
]


class Downstream:
    """下游服务：同一个幂等键只执行一次。"""

    def __init__(self) -> None:
        self.done: list[str] = []

    def call(self, key: str, idempotent: bool) -> str:
        if idempotent and key in self.done:
            return "已存在，跳过"
        self.done.append(key)
        return "执行"


def save_ckpt(path: Path, done: int) -> None:
    path.write_text(json.dumps({"done": done}), encoding="utf-8")


def load_ckpt(path: Path) -> int:
    return json.loads(path.read_text(encoding="utf-8"))["done"]


def run(steps: list[Step], start: int, svc: Downstream, ckpt: Path,
        idempotent: bool) -> tuple[int, list[str]]:
    """从第 start 步开始跑完，每完成一步写检查点。"""
    log: list[str] = []
    done = start - 1
    for s in steps[start - 1:]:
        if s.effect:
            log.append(f"步骤{s.idx} {s.name} -> {svc.call(s.effect, idempotent)}")
        else:
            log.append(f"步骤{s.idx} {s.name} -> 完成")
        done = s.idx
        save_ckpt(ckpt, done)
    return done, log


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def fresh() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()


def case_replay() -> Counter:
    print("  A 没有检查点：整轮重跑")
    ckpt = WORK / "a.json"
    svc = Downstream()
    run(STEPS, 1, svc, ckpt, idempotent=False)
    # 第 3 步之后进程退出，用户两小时后回来，从第一步重新跑
    run(STEPS, 1, svc, ckpt, idempotent=False)
    print(f"    下游被调用 {len(svc.done)} 次：{svc.done[:3]} + {svc.done[3:]}")
    return Counter(svc.done)


def case_resume() -> Counter:
    print("  B 有检查点：从第 3 步之后续跑")
    ckpt = WORK / "b.json"
    svc = Downstream()
    run(STEPS[:3], 1, svc, ckpt, idempotent=False)
    done = load_ckpt(ckpt)
    print(f"    进程退出时检查点记录：done={done}")
    at = datetime(2026, 3, 2, 9, 0) + timedelta(hours=2)
    print(f"    两小时后恢复（{at.strftime('%H:%M')}），从第 {done + 1} 步继续")
    run(STEPS, done + 1, svc, ckpt, idempotent=False)
    print(f"    下游被调用 {len(svc.done)} 次：{svc.done}")
    return Counter(svc.done)


def case_crash_before_ckpt() -> Counter:
    print("  C 崩在副作用之后、写检查点之前（靠幂等键兜住）")
    ckpt = WORK / "c.json"
    svc = Downstream()
    run(STEPS[:2], 1, svc, ckpt, idempotent=False)
    # 第 3 步的副作用已经发生，但进程在这里退出，检查点还停在 2
    svc.call(STEPS[2].effect or "", idempotent=True)
    done = load_ckpt(ckpt)
    print(f"    副作用已发生，检查点仍为 done={done}")
    _, log = run(STEPS, done + 1, svc, ckpt, idempotent=True)
    print(f"    {log[0]}")
    print(f"    下游被调用 {len(svc.done)} 次：{svc.done}")
    return Counter(svc.done)


def main() -> None:
    fresh()
    print("=== 1. 五个步骤，三个副作用 ===")
    for s in STEPS:
        mark = f"副作用 {s.effect}" if s.effect else ""
        print(f"  第 {s.idx} 步 {pad(s.name, 18)}{mark}")

    print()
    print("=== 2. 三种恢复方式 ===")
    a = case_replay()
    print()
    b = case_resume()
    print()
    c = case_crash_before_ckpt()

    print()
    print("=== 3. 每个副作用被执行了几次 ===")
    keys = ["email:A1001", "file:policy.md", "notify:A1001"]
    print("  方式  " + "".join(pad(k, 18) for k in keys))
    for label, counts in (("A 重跑", a), ("B 续跑", b), ("C 幂等", c)):
        print(f"  {pad(label, 8)}" + "".join(pad(str(counts.get(k, 0)), 18) for k in keys))
    print("  <- A 的邮件发了两次；B、C 各一次，区别在 B 靠检查点、C 靠幂等键")

    print()
    print("=== 4. 两小时那条时间线 ===")
    t0 = datetime(2026, 3, 2, 9, 0)
    marks = [
        (t0, "用户确认审批，开始执行"),
        (t0 + timedelta(minutes=1), "第 1-3 步完成，第 3 步已发出邮件，检查点 done=3"),
        (t0 + timedelta(minutes=2), "进程退出（用户关掉了页面）"),
        (t0 + timedelta(hours=2), "重新打开，读检查点 done=3"),
        (t0 + timedelta(hours=2, minutes=1), "从第 4 步继续，第 3 步不再执行"),
    ]
    for ts, what in marks:
        print(f"  {ts.strftime('%H:%M')}  {what}")
    print(f"  中断时长：{(marks[3][0] - marks[2][0]).total_seconds() / 3600:.0f} 小时")

    shutil.rmtree(WORK)


if __name__ == "__main__":
    main()
