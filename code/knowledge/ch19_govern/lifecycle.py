"""文档生命周期、条目结构与矛盾检测、可溯源率。

不联网。示例把"知识库"做成一个可增量更新的小索引：
文档有版本号，块带 doc_id + version + 定位信息；
更新时先删旧版本块再插新版本，删除同理（软删 + 检索过滤）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    doc_id: str
    version: int
    locator: str            # 可溯源定位：条款号或字符偏移
    text: str
    active: bool = True


class Store:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []

    def upsert_doc(self, doc_id: str, version: int, sections: list[tuple[str, str]]) -> dict:
        """整篇替换：把该文档的旧版本块置为失效，再插入新块。"""
        old = [c for c in self.chunks if c.doc_id == doc_id and c.active]
        for c in old:
            c.active = False
        for loc, text in sections:
            self.chunks.append(Chunk(doc_id, version, loc, text))
        return {"invalidated": len(old), "inserted": len(sections)}

    def delete_doc(self, doc_id: str) -> int:
        n = 0
        for c in self.chunks:
            if c.doc_id == doc_id and c.active:
                c.active = False
                n += 1
        return n

    def search(self, query: str, top: int = 3) -> list[Chunk]:
        live = [c for c in self.chunks if c.active]
        q = set(query)
        scored = [(sum(1 for ch in q if ch in c.text) / len(q), c) for c in live]
        scored = [x for x in scored if x[0] >= 0.5]      # 查询里一半以上的字要出现
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top]]

    def stats(self) -> dict:
        live = [c for c in self.chunks if c.active]
        return {"total": len(self.chunks), "active": len(live),
                "docs": len({c.doc_id for c in live})}


# ---------------------------------------------------------------- 条目结构

@dataclass
class Entry:
    """治理条目：要点 + 例外 + 来源。三段缺一段就不能用。"""
    key: str
    point: str
    exceptions: list[str] = field(default_factory=list)
    source: str = ""

    def complete(self) -> bool:
        return bool(self.point and self.source)


CONFLICT_PAIRS = [
    ("refund_window", "签收后7天内可退", "签收后15天内可退"),
    ("refund_window", "生鲜不支持无理由退货", "所有商品7天无理由"),
    ("shipping_fee", "质量问题运费商家承担", "退货一律买家承担运费"),
]


def num_in(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def detect_conflict(a: Entry, b: Entry) -> str | None:
    """同一 key 下，数字不一致或语义相反，都算矛盾。"""
    if a.key != b.key:
        return None
    if num_in(a.point) and num_in(b.point) and num_in(a.point) != num_in(b.point):
        return f"同一 key 的两个数字不同：{sorted(num_in(a.point))} vs {sorted(num_in(b.point))}"
    if ("不支持" in a.point) != ("不支持" in b.point):
        return "一个说支持、一个说不支持"
    return None


def traceable_rate(answers: list[dict]) -> float:
    """可溯源率：有来源且来源能定位到具体条目的答案占比。"""
    ok = 0
    for a in answers:
        src = a.get("source", "")
        loc = a.get("locator", "")
        if src and loc:
            ok += 1
    return ok / len(answers) if answers else 0.0


def main() -> None:
    s = Store()

    print("=== 1. 首次入库 ===")
    v1 = [
        ("第3条", "质量问题退货，运费由商家承担，签收后7天内提交凭证。"),
        ("第4条", "非质量问题退货，商品需保持未拆封，运费由买家承担。"),
    ]
    print(" ", s.upsert_doc("policy-return", 1, v1), s.stats())

    print()
    print("=== 2. 政策改动：7 天 -> 15 天，整篇替换 ===")
    v2 = [
        ("第3条", "质量问题退货，运费由商家承担，签收后15天内提交凭证。"),
        ("第4条", "非质量问题退货，商品需保持未拆封，运费由买家承担。"),
    ]
    s.upsert_doc("policy-return", 2, v2)
    print(" ", s.stats())
    print("  检索'15天内提交凭证' ->",
          [(c.doc_id, c.version, c.locator) for c in s.search("15天内提交凭证")])
    print("  检索'未拆封运费买家' ->",
          [(c.doc_id, c.version, c.locator) for c in s.search("未拆封运费买家")])
    print("  只有 v2 的块在服务，旧块已失效但仍在存储里（可回溯）")

    print()
    print("=== 3. v3 删掉第 4 条：只保留第 3 条 ===")
    s.upsert_doc("policy-return", 3, v1[:1])
    print(" ", s.stats())
    print("  检索'未拆封运费买家' ->",
          [c.locator for c in s.search("未拆封运费买家")] or "无命中（该条已失效）")
    print("  检索'质量问题运费商家' ->", [c.locator for c in s.search("质量问题运费商家")])
    print("  检索旧说法'7天内提交凭证' ->",
          [(c.version, c.locator) for c in s.search("7天内提交凭证")] or "无命中")

    print()
    print("=== 3.1 检索过滤失效块的效果：同一次查询，加不加 active 过滤 ===")
    q = "未拆封运费买家"
    live = [(c.version, c.locator) for c in s.search(q)]
    allv = [(c.version, c.locator, c.active) for c in s.chunks if q[:2] in c.text]
    print(f"  只查 active：{live or '无'}")
    print(f"  不加过滤：  {allv}")

    print()
    print("=== 4. 条目结构：要点 / 例外 / 来源 ===")
    good = Entry("refund_window", "签收后7天内可退",
                 ["生鲜类不支持无理由退货", "定制商品不支持"], source="policy-return#3")
    bad = Entry("refund_window", "签收后7天内可退", [], source="")
    for e in (good, bad):
        print(f"  {e.key}: 完整={e.complete()} 例外数={len(e.exceptions)} 来源={e.source or '（缺）'}")

    print()
    print("=== 5. 两条互相矛盾的条目 ===")
    for key, a, b in CONFLICT_PAIRS:
        why = detect_conflict(Entry(key, a), Entry(key, b))
        print(f"  {key}: {a!r} vs {b!r}")
        print(f"    -> {why or '未检出（需要人工判）'}")

    print()
    print("=== 6. 可溯源率 ===")
    answers = [
        {"text": "可以退", "source": "policy-return", "locator": "第3条"},
        {"text": "可以退", "source": "policy-return", "locator": ""},
        {"text": "可以退", "source": "", "locator": ""},
        {"text": "可以退", "source": "policy-return", "locator": "第4条"},
    ]
    print(f"  4 条答案中可溯源的 {int(traceable_rate(answers) * 4)} 条，可溯源率 {traceable_rate(answers):.0%}")
    print("  <- 只看'有引用'会算成 75%，要求定位到条目才是 50%")


if __name__ == "__main__":
    main()
