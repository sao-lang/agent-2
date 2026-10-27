"""长期记忆的三层写入与召回，以及租户隔离和软删除。

不联网。用 dict 当存储层，键里带租户前缀；删除用软删除，召回时必须过滤。
三层各自解决一类问题：语义（事实）、情景（某次经历）、程序（做法）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Record:
    kind: str                 # semantic / episodic / procedural
    tenant: str
    key: str
    text: str
    created_at: float
    deleted: bool = False
    source: str = ""          # 来源：哪次会话、哪份文档


class Deduper:
    """写入前去重：同一件事只留一条最新。"""

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}

    def new(self, text: str) -> bool:
        key = text.strip()
        if key in self.seen:
            return False
        self.seen[key] = text
        return True


class Memory:
    def __init__(self) -> None:        self.rows: dict[str, Record] = {}

    # ---------- 写入 ----------

    def write(self, rec: Record) -> str:
        """键里带租户前缀。不带的话，两个租户的同名键会互相覆盖。"""
        rid = f"{rec.tenant}/{rec.kind}/{rec.key}"
        self.rows[rid] = rec
        return rid

    def forget(self, tenant: str, kind: str, key: str) -> None:
        """软删除：标记而不是移除，保留审计痕迹。"""
        rid = f"{tenant}/{kind}/{key}"
        if rid in self.rows:
            self.rows[rid].deleted = True

    # ---------- 召回 ----------

    def recall(self, tenant: str, needle: str, kinds: tuple[str, ...] = ("semantic",),
               top: int = 3) -> list[Record]:
        """只在本租户的、未删除的记录里按字面重合度召回。"""
        hits = []
        for rid, r in self.rows.items():
            if r.tenant != tenant or r.deleted or r.kind not in kinds:
                continue
            score = sum(1 for ch in set(needle) if ch in r.text)
            if score:
                hits.append((score, r))
        hits.sort(key=lambda x: -x[0])
        return [r for _, r in hits[:top]]

    def dump(self) -> None:
        for rid, r in self.rows.items():
            flag = " (已删)" if r.deleted else ""
            print(f"  {rid:<34} {r.text[:26]}{flag}")


def main() -> None:
    m = Memory()
    t0 = time.time()

    print("=== 1. 三层各写一条 ===")
    m.write(Record("semantic", "t1", "pref_contact", "用户偏好工作日 9-18 点联系", t0, source="s-101"))
    m.write(Record("episodic", "t1", "last_refund", "上次退款因商品有瑕疵，全额退款并补了 10 元券", t0,
                   source="ticket-8821"))
    m.write(Record("procedural", "t1", "refund_flow", "瑕疵订单先要照片，再走质量问题通道，运费商家承担", t0,
                   source="skill:refund-review"))
    m.write(Record("semantic", "t2", "pref_contact", "用户偏好邮件联系", t0, source="s-901"))
    m.dump()

    print()
    print("=== 2. 三条不同的问题，各自该召回哪一层 ===")
    for q, kinds in (
        ("上班时间方便联系", ("semantic",)),
        ("上次这种情况是怎么处理的", ("episodic",)),
        ("瑕疵订单退款怎么走", ("procedural",)),
    ):
        hits = m.recall("t1", q, kinds=kinds)
        label = kinds[0]
        print(f"  {q:<16} -> {label:<11} " + ("；".join(r.text[:24] for r in hits) or "（无）"))
    print("  <- 三层召回的触发条件不同：问偏好、问历史、问做法")

    print()
    print("=== 3. 租户隔离：t2 查不到 t1 的东西 ===")
    print(f"  t1 查'偏好联系' -> {[r.text for r in m.recall('t1', '偏好联系')]}")
    print(f"  t2 查'偏好联系' -> {[r.text for r in m.recall('t2', '偏好联系')]}")

    print()
    print("=== 4. 软删除之后召回为空，记录仍在 ===")
    m.forget("t1", "semantic", "pref_contact")
    print(f"  t1 查'偏好联系' -> {[r.text for r in m.recall('t1', '偏好联系')]}")
    print("  存储里仍保留（用于审计）：")
    m.dump()

    print()
    print("=== 5. 一个容易做错的地方：键里不带租户 ===")
    m2 = Memory()
    m2.rows["t1/semantic/pref"] = Record("semantic", "t1", "pref", "A 用户偏好电话", t0)
    m2.rows["t2/semantic/pref"] = Record("semantic", "t2", "pref", "B 用户偏好邮件", t0)
    leak = [r for r in m2.rows.values() if r.key == "pref"]
    print(f"  按 key 查（不带租户）-> {[r.text for r in leak]}  <- 两个租户的数据混在一起")
    safe = [r for r in m2.rows.values() if r.tenant == "t1" and r.key == "pref"]
    print(f"  按 (tenant, key) 查   -> {[r.text for r in safe]}")

    print()
    print("=== 6. 同一批抽取结果，去重前后 ===")
    dedup = Deduper()
    facts = ["用户偏好电话联系", "用户偏好电话联系", "用户住杭州", "用户偏好电话联系"]
    kept = [f for f in facts if dedup.new(f)]
    print(f"  4 条抽取结果，去重后留下 {len(kept)} 条：{kept}")
    print("  不去重时，重复条目会占满召回前几名（与第 15 章 3.2 的近重复块同源）")


if __name__ == "__main__":
    main()
