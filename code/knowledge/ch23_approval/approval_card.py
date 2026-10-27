"""审批卡片：字段、状态机、有效期、幂等。

不联网。时钟是固定的（演示用），这样状态流转的顺序可以精确复现。
卡片上的每个字段都对应一个具体的失败：缺影响范围 → 审的人不知道在批什么；
缺有效期 → 三天后通过一个已经过时的动作；缺参数指纹 → 同一个动作被批两次。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

BASE = datetime(2026, 3, 2, 9, 0)
TTL_MIN = 15


@dataclass
class Card:
    cid: str
    step: int
    tool: str
    digest: str            # 参数指纹：参数变了，指纹就变
    summary: str           # 一句话说清要做什么
    impact: str            # 影响谁
    reversible: bool
    ttl_min: int
    created: datetime
    status: str = "pending"
    decided_at: datetime | None = None
    decided_by: str | None = None

    @property
    def deadline(self) -> datetime:
        return self.created + timedelta(minutes=self.ttl_min)


class Store:
    def __init__(self) -> None:
        self.cards: list[Card] = []
        self._seq = 1000

    def submit(self, step: int, tool: str, digest: str, summary: str,
               impact: str, reversible: bool, now: datetime) -> tuple[Card, str]:
        """同一 step 同一指纹只留一张卡；指纹变了，旧卡作废。"""
        for c in self.cards:
            if c.step == step and c.digest == digest:
                return c, f"已有卡片 {c.cid}（{c.status}），不重复提交"
        old = [c for c in self.cards if c.step == step and c.status in ("pending", "approved")]
        for c in old:
            c.status = "superseded"
        self._seq += 1
        card = Card(f"A-{self._seq}", step, tool, digest, summary, impact,
                    reversible, TTL_MIN, now)
        self.cards.append(card)
        note = f"新卡片 {card.cid}"
        if old:
            note += f"，作废 {', '.join(c.cid for c in old)}"
        return card, note

    def decide(self, card: Card, approved: bool, who: str, now: datetime) -> str:
        if card.status != "pending":
            return f"无效操作：当前状态 {card.status}"
        if now > card.deadline:
            card.status = "expired"
            return "已过期：需要按当前情况重新提交"
        card.status = "approved" if approved else "rejected"
        card.decided_at, card.decided_by = now, who
        return card.status


def stamp(now: datetime) -> str:
    minutes = int((now - BASE).total_seconds() // 60)
    return f"t+{minutes}m"


def show(card: Card) -> None:
    print(f"    {card.cid}  step={card.step}/{card.tool}  指纹={card.digest}")
    print(f"      动作：{card.summary}")
    print(f"      影响：{card.impact}  可回滚：{'是' if card.reversible else '否'}")
    print(f"      有效期：{card.ttl_min} 分钟（截止 {card.deadline.strftime('%H:%M')}）")
    if card.decided_at:
        print(f"      决定：{card.status} by {card.decided_by} "
              f"@ {card.decided_at.strftime('%H:%M')}")


def main() -> None:
    s = Store()
    print("=== 1. 一张卡片长什么样 ===")
    c1, _ = s.submit(3, "write_file", "9f3a",
                     "覆写 policy.md：把 15 天改成 365 天",
                     "所有退货咨询", False, BASE)
    show(c1)

    print()
    print("=== 2. 状态流转 ===")
    print(f"  {stamp(BASE):<8}提交 -> {c1.status}")

    t = BASE + timedelta(minutes=3)
    print(f"  {stamp(t):<8}通过（张三） -> {s.decide(c1, True, '张三', t)}")

    t = BASE + timedelta(minutes=20)
    c, note = s.submit(3, "write_file", "9f3a", "覆写 policy.md：把 15 天改成 365 天",
                       "所有退货咨询", False, t)
    print(f"  {stamp(t):<8}同一动作被再次提交 -> {note}")

    t = BASE + timedelta(minutes=40)
    c2, note = s.submit(3, "write_file", "b71c", "覆写 policy.md：把 15 天改成 90 天",
                        "所有退货咨询", False, t)
    print(f"  {stamp(t):<8}参数改了一个数字 -> {note}")
    print(f"  {"":<8}{c1.cid} 现在是 {c1.status}（旧卡不能再被通过）")

    t = BASE + timedelta(minutes=50)
    print(f"  {stamp(t):<8}通过（李四） -> {s.decide(c2, True, '李四', t)}")

    t = BASE + timedelta(minutes=60)
    c3, _ = s.submit(5, "send_email", "e004", "给客户 A1001 发退款邮件",
                     "单个外部客户", False, t)
    t = BASE + timedelta(minutes=80)
    print(f"  {stamp(t):<8}对 {c3.cid} 点通过 -> {s.decide(c3, True, '王五', t)}")

    print()
    print("=== 3. 卡片总览 ===")
    for c in s.cards:
        print(f"  {c.cid}  step={c.step}  {c.digest}  {c.status:<10} {c.summary}")

    print()
    print("=== 4. 三张卡：一张作废、一张通过、一张超时 ===")
    print("  幂等靠指纹：同一动作重复提交返回同一张卡")
    print("  参数变了必须重新审：旧卡作废，因为它批准的是另一个动作")
    print("  过期由查询时判定：不依赖定时任务扫表")


if __name__ == "__main__":
    main()
