"""第 20 章 step4：人不在怎么办 —— 超时与降级（离线）。

运行：
    python code/ch20_hitl/step4_timeout_escalation.py

上一级的痛点：中断与恢复都能跑了，但**人不在**这个最常见的情况还没处理。
这一级做什么：把"等人"的四种结局都跑一遍，并证明一个反直觉的结论——

    **超时默认放行，比超时默认拒绝更危险。**

四种情况：
  A. 人及时批准     → 执行
  B. 人及时拒绝     → 不执行
  C. 没人理，超时   → 按策略处理（本章：不执行 + 升级）
  D. 卡片过期后才批 → 必须作废，不能执行
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

APPROVAL_TTL = 300  # 秒


class TimeoutPolicy(str, Enum):
    DENY = "deny"          # 超时 = 不执行（本章的选择）
    ALLOW = "allow"        # 超时 = 放行（危险）
    ESCALATE = "escalate"  # 超时 = 转给上级


@dataclass
class Ticket:
    """一个待审批请求。"""

    request_id: str
    action: str
    args: dict
    level: str
    created_at: float = field(default_factory=time.time)
    ttl: float = APPROVAL_TTL
    decided_at: float | None = None
    decision: str | None = None
    escalations: int = 0

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) > self.expires_at


def settle(t: Ticket, now: float, policy: TimeoutPolicy) -> tuple[str, str]:
    """决定一个工单最终怎么处理。返回 (结局, 说明)。"""
    if t.decision is not None:
        if t.is_expired(t.decided_at or now):
            return "作废", "卡片已过期才审批 -> 必须重新发起，不能直接执行"
        return ("执行" if t.decision == "approve" else "拒绝",
                f"人在 {int(t.decided_at - t.created_at)} 秒内处理")

    if not t.is_expired(now):
        return "等待中", "还没超时"

    if policy is TimeoutPolicy.DENY:
        return "拒绝", "超时 -> 安全默认是『不做』"
    if policy is TimeoutPolicy.ALLOW:
        return "执行", "超时 -> 放行（危险：等于没人看也能执行）"
    return "升级", f"超时 -> 转上级（第 {t.escalations + 1} 次升级）"


def main() -> None:
    t0 = time.time()

    print("=" * 78)
    print("四种情况，同一套规则")
    print("=" * 78)

    cases = [
        ("A 及时批准", dict(decided_at=t0 + 40, decision="approve")),
        ("B 及时拒绝", dict(decided_at=t0 + 40, decision="reject")),
        ("C 没人理（超时）", dict(decision=None)),
        ("D 过期后才批", dict(decided_at=t0 + 900, decision="approve")),
    ]

    print(f"{'情况':<18}{'deny 策略':<14}{'allow 策略':<14}{'escalate 策略'}")
    print("-" * 78)
    for label, extra in cases:
        row = []
        for policy in (TimeoutPolicy.DENY, TimeoutPolicy.ALLOW, TimeoutPolicy.ESCALATE):
            t = Ticket("r-1", "refund", {"amount": 299}, "confirm", created_at=t0, ttl=APPROVAL_TTL)
            for k, v in extra.items():
                setattr(t, k, v)
            outcome, _ = settle(t, now=t0 + 1000, policy=policy)
            row.append(outcome)
        print(f"{label:<18}{row[0]:<14}{row[1]:<14}{row[2]}")

    print("\n" + "=" * 78)
    print("★ 为什么『超时放行』更危险")
    print("=" * 78)
    print("  超时放行 = 只要没人看，动作就自动执行。")
    print("  而『没人看』恰恰是最常见的情况：")
    print("    · 夜间 / 周末 / 节假日")
    print("    · 审批人离职或调岗")
    print("    · 消息推送到一个没人看的群")
    print()
    print("  结果就是：你设计了一套审批流程，但它**在最需要它的时候失效**。")
    print("  更糟的是日志里会显示『已审批通过』——看起来一切正常。")

    print("\n" + "=" * 78)
    print("三种超时策略，什么时候用哪个")
    print("=" * 78)
    print(f"  {'策略':<12}{'适用':<30}{'代价'}")
    print("  " + "-" * 70)
    print(f"  {'deny':<12}{'不可逆动作（退款、删数据）':<30}{'任务卡住，需人工补做'}")
    print(f"  {'allow':<12}{'几乎不可用（只在极低风险）':<30}{'静默执行，事后才知道'}")
    print(f"  {'escalate':<12}{'有人可接班（值班表）':<30}{'需要真正的值班机制'}")

    print("\n" + "=" * 78)
    print("升级链：别只往上丢一次")
    print("=" * 78)
    t = Ticket("r-2", "refund", {"amount": 9999}, "confirm", created_at=t0)
    chain = ["一线客服", "客服主管", "运营负责人", "值班经理"]
    for i, who in enumerate(chain, 1):
        print(f"  第 {i} 级：转给 {who}")
        if i < len(chain):
            print(f"          {APPROVAL_TTL} 秒内无人处理 -> 继续升级")
    print("  → 全都没人 -> 走 deny（不执行），并写入『需人工补做』队列。")
    print()
    print("  ⚠️ 升级链必须有**终点**。否则会像告警风暴一样，")
    print("     最后所有人都学会了忽略它。")

    print("\n" + "=" * 78)
    print("三个容易做错的地方")
    print("=" * 78)
    print("  1. 过期后仍然执行")
    print("     卡片写着『有效期 5 分钟』，但代码只在生成时算了一次时间戳，")
    print("     审批时根本没检查。→ 三周后有人点了个『批准』，退款真的发了。")
    print()
    print("  2. 超时后不清理，任务永远挂在 pending")
    print("     列表越来越长，告警越来越多，最后没人看。")
    print()
    print("  3. 升级没有去重")
    print("     同一个人被升级了 5 次，收到 5 条一样的通知 —— 他会把整个通知渠道静音。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  默认拒绝 + 明确的升级链 + 过期作废。")
    print("  这三条决定了『人不在』时系统是安全地停下来，还是危险地继续跑。")


if __name__ == "__main__":
    main()
