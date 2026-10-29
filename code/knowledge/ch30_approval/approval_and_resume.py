"""第 30 章示例：审批卡片、审批状态机、中断两小时后恢复。

不联网，只用标准库。审批卡片与检查点都真的写在文件里：
"进程退出"之后重新从磁盘加载，证明审批状态不依赖进程内存。
三个场景共用同一个 Gate：没有有效批准的副作用，一律在执行前被拦下。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

WORK = Path(__file__).with_name("_run")
BASE = datetime(2026, 3, 2, 9, 0)


# ---------------------------------------------------------------- 分级

@dataclass
class Action:
    tool: str
    what: str
    reversible: bool
    scope: str          # self / team / global / external


def level(a: Action) -> int:
    """可逆性与影响范围两个字段，决定四级审批。"""
    if a.scope == "self" and a.reversible:
        return 1
    if not a.reversible and a.scope in ("global", "external"):
        return 4
    if not a.reversible or a.scope in ("global", "external"):
        return 3
    return 2


LEVEL_TEXT = {
    1: "L1 自动执行",
    2: "L2 执行后留存，可回滚",
    3: "L3 事前审批（单人）",
    4: "L4 事前审批（双人）+ 冷却期",
}

ACTIONS = [
    Action("read_file", "读 src/app.py", True, "self"),
    Action("write_file", "写临时目录 build/tmp/out.json", True, "self"),
    Action("run_tests", "跑 pytest", True, "self"),
    Action("write_file", "改 src/app.py", True, "team"),
    Action("git_commit", "提交到本地分支", True, "team"),
    Action("rollback", "回滚上次迁移（有快照）", True, "team"),
    Action("call_api", "调外部汇率 API", True, "external"),
    Action("write_config", "改生产配置（有快照）", True, "global"),
    Action("send_email", "给客户发一封邮件", False, "external"),
    Action("delete_rows", "删掉 30 天前的订单", False, "global"),
    Action("deploy", "发布到生产环境", False, "global"),
]


# ---------------------------------------------------------------- 审批卡片

def fingerprint(tool: str, args: dict) -> str:
    """参数指纹：键排序、紧凑分隔，参数改一个字符指纹就变。"""
    raw = json.dumps({"tool": tool, "args": args}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


@dataclass
class Card:
    cid: str
    run_id: str
    step: int
    tool: str
    args: dict
    digest: str
    summary: str
    impact: str
    reversible: bool
    ttl_min: int
    created: datetime
    status: str = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    executed_at: datetime | None = None
    history: list[str] = field(default_factory=list)

    @property
    def deadline(self) -> datetime:
        return self.created + timedelta(minutes=self.ttl_min)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("created", "decided_at", "executed_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        d = dict(d)
        for k in ("created", "decided_at", "executed_at"):
            d[k] = datetime.fromisoformat(d[k]) if d[k] else None
        return cls(**d)


class CardStore:
    """审批卡片落在文件里：进程退出后仍能读到上一张卡的状态。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.cards: dict[str, Card] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.cards = {cid: Card.from_dict(d) for cid, d in data.items()}
        self._seq = 1000 + len(self.cards)

    def save(self) -> None:
        data = {cid: c.to_dict() for cid, c in self.cards.items()}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def get(self, cid: str | None) -> Card | None:
        return self.cards.get(cid) if cid else None

    def submit(self, run_id: str, step: int, tool: str, args: dict, summary: str,
               impact: str, reversible: bool, ttl_min: int,
               now: datetime) -> tuple[Card, str]:
        digest = fingerprint(tool, args)
        for c in self.cards.values():
            if c.run_id == run_id and c.step == step and c.digest == digest:
                return c, f"已有卡片 {c.cid}（{c.status}），不重复提交"
        old = [c for c in self.cards.values()
               if c.run_id == run_id and c.step == step
               and c.status in ("pending", "approved")]
        for c in old:
            c.status = "superseded"
            c.history.append(f"{now:%H:%M} superseded（参数已变）")
        self._seq += 1
        card = Card(f"A-{self._seq}", run_id, step, tool, args, digest,
                    summary, impact, reversible, ttl_min, now)
        card.history.append(f"{now:%H:%M} pending（提交）")
        self.cards[card.cid] = card
        self.save()
        note = f"新卡片 {card.cid}"
        if old:
            note += f"，作废 {', '.join(c.cid for c in old)}"
        return card, note

    def decide(self, card: Card, approved: bool, who: str,
               now: datetime) -> str:
        if card.status != "pending":
            return f"无效操作：当前状态 {card.status}"
        if now > card.deadline:
            card.status = "expired"
            card.history.append(f"{now:%H:%M} expired（点通过时已过期）")
            self.save()
            return "已过期：需要按当前情况重新提交"
        card.status = "approved" if approved else "rejected"
        card.decided_by, card.decided_at = who, now
        card.history.append(f"{now:%H:%M} {card.status}（{who}）")
        self.save()
        return card.status

    def mark_resumed(self, card: Card, now: datetime) -> None:
        card.status = "resumed"
        card.executed_at = now
        card.history.append(f"{now:%H:%M} resumed（恢复后执行）")
        self.save()


class Blocked(Exception):
    """审批闸门拦下的执行。"""


def gate_execute(card: Card | None, tool: str, args: dict, store: CardStore,
                 now: datetime) -> str:
    """唯一的执行入口：卡片、状态、有效期、指纹四项都过才放行。"""
    if card is None:
        raise Blocked("拦下：没有审批卡片，动作未提交")
    if card.status == "pending":
        raise Blocked("拦下：卡片仍是 pending，没有人点过同意")
    if card.status in ("rejected", "expired", "superseded"):
        raise Blocked(f"拦下：卡片状态为 {card.status}")
    if card.status != "approved":
        raise Blocked(f"拦下：卡片状态为 {card.status}，不能再次执行")
    if now > card.deadline:
        card.status = "expired"
        card.history.append(f"{now:%H:%M} expired（执行前校验）")
        store.save()
        raise Blocked(f"拦下：卡片已于 {card.deadline:%H:%M} 过期")
    if card.digest != fingerprint(tool, args):
        raise Blocked("拦下：参数指纹不符，批准的与要执行的不是同一个动作")
    store.mark_resumed(card, now)
    return f"放行：{tool} 执行，卡片 {card.cid} -> resumed"


# ---------------------------------------------------------------- 检查点

@dataclass
class Checkpoint:
    run_id: str
    step: int
    state: dict
    plan_version: int = 1
    pending_step: dict | None = None
    approval_cid: str | None = None


def save_cp(path: Path, cp: Checkpoint) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp.__dict__, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def load_cp(path: Path) -> Checkpoint:
    d = json.loads(path.read_text(encoding="utf-8"))
    return Checkpoint(**d)


# ---------------------------------------------------------------- 场景

def stamp(now: datetime) -> str:
    minutes = int((now - BASE).total_seconds() // 60)
    return f"t+{minutes}m"


def show_card(card: Card) -> None:
    print(f"  卡片 {card.cid}")
    print(f"    run_id      : {card.run_id}")
    print(f"    步骤        : 第 {card.step} 步 / {card.tool}")
    print(f"    参数        : {json.dumps(card.args, ensure_ascii=False)}")
    print(f"    digest      : {card.digest}")
    print(f"    动作        : {card.summary}")
    print(f"    影响        : {card.impact}")
    print(f"    可回滚      : {'是' if card.reversible else '否'}")
    print(f"    有效期      : {card.ttl_min} 分钟（截止 {card.deadline:%H:%M}）")
    print(f"    状态        : {card.status}")
    print(f"    决定        : {card.decided_by or '-'} / "
          f"{card.decided_at:%H:%M}" if card.decided_at else "    决定        : -")
    print(f"    执行时间    : {card.executed_at:%H:%M}" if card.executed_at
          else "    执行时间    : -")
    print("    历史        : " + " -> ".join(card.history))


def scenario_levels() -> None:
    print("=== 1. 十一个动作的分级 ===")
    print(f"  {'工具':<13}{'动作':<30}{'可逆':<4}{'范围':<10}级别")
    for a in ACTIONS:
        lv = level(a)
        print(f"  {a.tool:<13}{a.what:<30}{'是' if a.reversible else '否':<4}"
              f"{a.scope:<10}{LEVEL_TEXT[lv]}")


def scenario_card(store: CardStore) -> Card:
    print()
    print("=== 2. 一张审批卡片：完整字段 ===")
    action = {"to": "customer:A1001", "subject": "退款确认",
              "body": "您的退款 199 元将在 3 个工作日内到账"}
    card, _ = store.submit(
        "run-30", 3, "send_email", action,
        "给客户 A1001 发退款确认邮件", "单个外部客户，邮件不可撤回",
        False, ttl_min=240, now=BASE + timedelta(minutes=2))
    show_card(card)

    return card


def run_until_exit(store: CardStore, cp_path: Path) -> Checkpoint:
    cp = Checkpoint("run-30", 0, {"order": "A1001", "facts": []})
    print("  --- 第一次执行（09:00 开始）---")
    for i, name in enumerate(["读政策文档", "算新期限"], 1):
        cp.step = i
        cp.state["facts"].append(f"{name}完成")
        save_cp(cp_path, cp)
        print(f"  {stamp(BASE + timedelta(minutes=i)):<8}第 {i} 步 {name} -> 完成，"
              f"检查点 step={cp.step}")

    action = {"to": "customer:A1001", "subject": "退款确认",
              "body": "您的退款 199 元将在 3 个工作日内到账"}
    summary = "给客户 A1001 发退款确认邮件"
    card = [c for c in store.cards.values()
            if c.run_id == "run-30" and c.step == 3][0]
    cp.pending_step = {"step": 3, "tool": "send_email", "args": action,
                       "summary": summary}
    cp.approval_cid = card.cid
    save_cp(cp_path, cp)
    print(f"  {stamp(BASE + timedelta(minutes=2)):<8}第 3 步提交审批 {card.cid}，"
          f"检查点记下 pending 与 approval_cid")
    result = store.decide(card, True, "张三", BASE + timedelta(minutes=3))
    print(f"  {stamp(BASE + timedelta(minutes=3)):<8}张三点通过 -> {result}")
    print(f"  {stamp(BASE + timedelta(minutes=4)):<8}进程退出，卡片留在磁盘上")
    return cp


def scenario_resume(store: CardStore, cp_path: Path, card: Card) -> None:
    print()
    print("=== 4. 中断 2 小时后恢复：仍用同一份检查点 ===")
    cp = load_cp(cp_path)
    print(f"  读检查点：run_id={cp.run_id} step={cp.step} "
          f"pending={cp.pending_step['tool']} approval={cp.approval_cid}")
    print(f"  检查点里没有 approved=true，只有 approval_cid；批准与否以卡片为准")
    now = BASE + timedelta(hours=2)
    fresh = CardStore(store.path)
    c = fresh.get(cp.approval_cid)
    print(f"  {now:%H:%M} 新进程从磁盘读回卡片 {c.cid}：status={c.status}，"
          f"digest={c.digest}")
    print(f"  {now:%H:%M} 校验卡片 {c.cid}：status={c.status}, "
          f"截止 {c.deadline:%H:%M}, digest={c.digest}")
    print("  " + gate_execute(c, cp.pending_step["tool"], cp.pending_step["args"],
                              fresh, now))

    cp.step = 3
    cp.state["facts"].append("退款确认邮件已发")
    cp.pending_step = None
    cp.approval_cid = None
    save_cp(cp_path, cp)
    print(f"  {now:%H:%M} 第 3 步提交完成，检查点 step=3")

    for i, name in enumerate(["写 policy.md", "发完成通知"], 4):
        cp.step = i
        cp.state["facts"].append(f"{name}完成")
        save_cp(cp_path, cp)
        at = now + timedelta(minutes=i - 3)
        print(f"  {at:%H:%M} 第 {i} 步 {name} -> 完成，检查点 step={cp.step}")

    print()
    print("=== 5. 恢复后的卡片：approved -> resumed ===")
    show_card(fresh.get(c.cid))
    print()
    print("=== 6. 两小时那条时间线 ===")
    marks = [
        (BASE, "开始执行"),
        (BASE + timedelta(minutes=1), "第 1 步完成，检查点 step=1"),
        (BASE + timedelta(minutes=2), "第 2 步完成，检查点 step=2"),
        (BASE + timedelta(minutes=2), "第 3 步提交审批 A-1001"),
        (BASE + timedelta(minutes=3), "张三通过；进程在 09:04 退出"),
        (now, "新进程读检查点 step=2 与 approval_cid=A-1001"),
        (now + timedelta(minutes=1), "校验卡片仍为 approved 且未过期，执行第 3 步"),
        (now + timedelta(minutes=2), "第 4-5 步完成，检查点 step=5"),
    ]
    for ts, what in marks:
        print(f"  {ts:%H:%M}  {what}")
    print(f"  中断时长：{(now - (BASE + timedelta(minutes=3))).total_seconds() / 3600:.0f} 小时")


def scenario_blocked(store: CardStore) -> None:
    print()
    print("=== 7. 未审批就执行：逐条被拦下 ===")
    tool = "delete_rows"
    args = {"table": "orders", "before": "2026-02-01"}

    cases: list[tuple[str, Card | None, datetime]] = []

    cases.append(("没有任何卡片", None, BASE + timedelta(minutes=10)))

    pending, _ = store.submit("run-31", 1, tool, args, "删掉 2 月前的订单",
                              "全量订单", False, 240,
                              BASE + timedelta(minutes=10))
    cases.append(("卡片还是 pending", pending, BASE + timedelta(minutes=11)))

    changed = dict(args, before="2026-03-01")
    approved, _ = store.submit("run-32", 1, "deploy", {"env": "prod"},
                               "发布到生产", "全部用户", False, 240,
                               BASE + timedelta(minutes=12))
    store.decide(approved, True, "李四", BASE + timedelta(minutes=13))
    cases.append(("批准的是 A，执行的是 B", approved, BASE + timedelta(minutes=14)))

    short, _ = store.submit("run-33", 1, tool, args, "删掉 2 月前的订单",
                            "全量订单", False, 15,
                            BASE + timedelta(minutes=15))
    store.decide(short, True, "王五", BASE + timedelta(minutes=16))
    cases.append(("有效期 15 分钟，两小时后再点", short,
                  BASE + timedelta(hours=2)))

    for label, card, at in cases:
        try:
            if label == "批准的是 A，执行的是 B":
                out = gate_execute(card, "deploy", changed, store, at)
            elif label == "有效期 15 分钟，两小时后再点":
                out = gate_execute(card, tool, args, store, at)
            else:
                out = gate_execute(card, tool, args, store, at)
        except Blocked as e:
            out = f"Blocked: {e}"
        print(f"  {label:<22}{out}")

    good, _ = store.submit("run-34", 1, tool, args, "删掉 2 月前的订单",
                           "全量订单", False, 240, BASE + timedelta(minutes=20))
    store.decide(good, True, "赵六", BASE + timedelta(minutes=21))
    print(f"  {'卡片已批准且参数一致':<22}"
          f"{gate_execute(good, tool, args, store, BASE + timedelta(minutes=22))}")


def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)

    scenario_levels()

    store = CardStore(WORK / "cards.json")
    card = scenario_card(store)
    cp_path = WORK / "checkpoint.json"

    print()
    print("=== 3. 第一次执行：pending -> approved，然后进程退出 ===")
    cp = run_until_exit(store, cp_path)
    print(f"  退出时检查点：step={cp.step} pending={cp.pending_step['step']} "
          f"approval={cp.approval_cid}")

    scenario_resume(store, cp_path, card)
    scenario_blocked(store)

    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
