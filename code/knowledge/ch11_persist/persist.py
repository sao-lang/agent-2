"""检查点、恢复与幂等：为什么恢复会发两封邮件。

不联网。用一个会"在第 3 步崩"的执行器，演示三种恢复方式的结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 副作用

@dataclass
class Outbox:
    """外部副作用（发短信）的替身。真实系统里这是一个不可回滚的调用。"""
    sent: list[str] = field(default_factory=list)

    def send(self, order_id: str) -> dict:
        self.sent.append(order_id)
        return {"sent": True, "seq": len(self.sent)}


# ---------------------------------------------------------------- 检查点

@dataclass
class Checkpoint:
    step: int
    done: list[str]
    state: dict
    pending_side_effect: bool = False
    effect_key: str | None = None


def save(path: str, cp: Checkpoint) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cp.__dict__, f, ensure_ascii=False)


def load(path: str) -> Checkpoint:
    with open(path, encoding="utf-8") as f:
        return Checkpoint(**json.load(f))


# ---------------------------------------------------------------- 执行器

STEPS = ["取订单", "取政策", "发通知", "汇总"]


def run_from(step_index: int, outbox: Outbox, crash_at: int,
             idempotent: bool, done_effects: set[str]) -> tuple[list[str], int]:
    """从第 step_index 步开始跑，到 crash_at 崩。返回 (日志, 完成到第几步)。"""
    log: list[str] = []
    for i in range(step_index, len(STEPS)):
        name = STEPS[i]
        if name == "发通知":
            key = "notify:A1001"
            if idempotent and key in done_effects:
                log.append(f"步 {i + 1} {name}: 已执行过，跳过")
            else:
                outbox.send("A1001")
                done_effects.add(key)
                log.append(f"步 {i + 1} {name}: 已发送")
        else:
            log.append(f"步 {i + 1} {name}: ok")
        if i == crash_at:
            log.append(f"步 {i + 1} 之后进程崩溃")
            return log, i
    return log, len(STEPS) - 1


def main() -> None:
    # 一、无检查点：只能从头重跑
    box = Outbox()
    log1, _ = run_from(0, box, crash_at=2, idempotent=False, done_effects=set())
    log1b, _ = run_from(0, box, crash_at=99, idempotent=False, done_effects=set())
    print("=== 一、无检查点 ===")
    print("\n".join("  " + l for l in log1 + log1b))
    print(f"  实际发送次数：{len(box.sent)}  内容：{box.sent}")

    # 二、有检查点、无幂等
    box = Outbox()
    effects: set[str] = set()
    log2a, done_step = run_from(0, box, crash_at=2, idempotent=False, done_effects=effects)
    log2b, _ = run_from(done_step, box, crash_at=99, idempotent=False, done_effects=effects)
    print()
    print("=== 二、有检查点、无幂等 ===")
    print("\n".join("  " + l for l in log2a))
    print("  ...进程重启...")
    print("\n".join("  " + l for l in log2b))
    print(f"  实际发送次数：{len(box.sent)}  内容：{box.sent}")

    # 三、有检查点 + 幂等键
    box = Outbox()
    effects = set()
    log3a, done_step = run_from(0, box, crash_at=2, idempotent=True, done_effects=effects)
    log3b, _ = run_from(done_step, box, crash_at=99, idempotent=True, done_effects=effects)
    print()
    print("=== 三、有检查点 + 幂等键 ===")
    print("\n".join("  " + l for l in log3a))
    print("  ...进程重启...")
    print("\n".join("  " + l for l in log3b))
    print(f"  实际发送次数：{len(box.sent)}  内容：{box.sent}")


if __name__ == "__main__":
    main()
