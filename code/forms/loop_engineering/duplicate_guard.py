"""重复动作被插点拦下：同一个副作用只执行一次。

不联网。场景是一个真实会发生的序列：发送通知 → 确认发送结果时超时 →
策略认为没发出去，重发同一封。插点 before_step 在第二次执行之前就拦住它。

运行：python code/forms/loop_engineering/duplicate_guard.py
"""

from __future__ import annotations

import json

from loop_core import Action, Hooks, Limits, Loop, digest

NOTICE = "订单 O7 支付失败，需人工核对"
TASK = "把订单 O7 的失败通知发出去，并确认对方收到"


class NotifyAPI:
    """最小的外部系统：有日志、没有幂等表（幂等由插点负责）。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, to: str, text: str) -> str:
        self.sent.append({"to": to, "text": text})
        return "已投递到网关，回执超时（第 %d 次）" % len(self.sent)


def fingerprint_demo() -> None:
    print("=== 0. 指纹对键序敏感会怎样 ===")
    a = {"to": "ops", "text": NOTICE}
    b = {"text": NOTICE, "to": "ops"}
    raw_a = digest(json.dumps(a, ensure_ascii=False))
    raw_b = digest(json.dumps(b, ensure_ascii=False))
    can_a = digest(json.dumps(a, ensure_ascii=False, sort_keys=True))
    can_b = digest(json.dumps(b, ensure_ascii=False, sort_keys=True))
    print(f"    未排序：A={raw_a} B={raw_b}  {'一致' if raw_a == raw_b else '不一致'}")
    print(f"    已排序：A={can_a} B={can_b}  {'一致' if can_a == can_b else '不一致'}")
    print("    指纹不稳定时，重复检测一定漏：同一动作被当成两个不同动作")


def make_policy():
    def policy(lp: Loop, obs: str) -> Action | None:
        attempts = lp.state.get("attempts", 0)
        if attempts == 0:
            return Action("send", "ops", NOTICE)
        if lp.last_result.startswith("已跳过"):
            return None
        if "超时" in lp.last_result:
            return Action("send", "ops", NOTICE)   # 策略：没确认收到就重发
        return None
    return policy


def make_act(api: NotifyAPI):
    def act(lp: Loop, action: Action) -> str:
        lp.state["attempts"] = lp.state.get("attempts", 0) + 1
        return api.send(action.target, action.payload)
    return act


def guard(lp: Loop, obs: str, action: Action | None) -> str | None:
    """before_step：拿计划中的动作去查账本，第二次就否决。"""
    if action is None:
        return None
    if lp.fp[action.fingerprint()] >= 1:
        return "repeated_action"
    return None


def count_side_effects(lp: Loop, action: Action, result: str) -> None:
    """after_action：副作用账本。只有真正执行过的动作才记账。"""
    if action.kind == "send":
        lp.fp[action.fingerprint()] += 1


def run(with_guard: bool) -> tuple[NotifyAPI, Loop]:
    api = NotifyAPI()
    hooks = Hooks(after_action=count_side_effects,
                  before_step=guard if with_guard else None)
    lp = Loop(f"dup-{int(with_guard)}", make_policy(), make_act(api), Limits(max_steps=6), hooks)
    lp.result = lp.run(TASK)
    return api, lp


def main() -> None:
    fingerprint_demo()
    print()

    print("=== 1. 没有 after_action + before_step：一路重发到步数上限 ===")
    api, lp = run(with_guard=False)
    print(f"    终止={lp.result.reason}  步数={lp.result.steps}  外部系统收到 {len(api.sent)} 次")
    for row in lp.records:
        print(f"    step={row['step']} {row['action']:<8} 指纹={row['action_hash']} verdict={row['verdict']}")
    print("    <- 六次指纹完全相同，但没有任何地方比较过它们")

    print()
    print("=== 2. 挂上 before_step 的重复检查：第二次在动作前被拦 ===")
    api2, lp2 = run(with_guard=True)
    print(f"    终止={lp2.result.reason}  步数={lp2.result.steps}  外部系统收到 {len(api2.sent)} 次")
    for row in lp2.records:
        print(f"    step={row['step']} {row['action']:<8} 指纹={row['action_hash']} verdict={row['verdict']}")
    print("    <- 拦截发生在 act 之前，外部系统只被打扰一次")

    print()
    print("=== 3. 两条终止路径的差别 ===")
    print(f"    拦下后终止原因={lp2.result.reason}，账本里该指纹计数={lp2.fp}")
    print("    重复动作是异常终止，不是失败：正确做法是停下并交给人确认投递状态")


if __name__ == "__main__":
    main()

