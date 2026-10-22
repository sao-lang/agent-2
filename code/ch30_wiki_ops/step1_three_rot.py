"""第 44 章 step1：一条"看着没问题"的条目，怎么骗过你自己的检查（离线）。

运行：
    python code/ch30_wiki_ops/step1_three_rot.py

上一级的痛点：第 29 章解决了"条目长什么样"，但没解决"条目会不会烂"。
这一级做什么：造三条**都能通过"格式检查"**的条目，然后证明格式检查一个都拦不住。

三条病：
  A. 来源是编的（sources 里的 chunk id 根本不存在，或里面没有那句话）
  B. 数字过时了（v1 说 7 天，v2 说 15 天，两条都还在库里）
  C. 例外被吞掉（原文有"不适用"，条目里没有）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402
from common.wiki import EntryStatus, EntryType, WikiEntry, WikiStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

# 三个"畸形"条目：格式全对，内容有问题
SICK: list[tuple[str, str, WikiEntry]] = [
    (
        "A 来源造假",
        "sources 指向 c99，但这个 chunk 不存在；即使存在，里面也没有这句话",
        WikiEntry(
            id="w-a", title="无理由退货", type=EntryType.RULE,
            definition="签收后 30 天内，商品未拆封的，可申请无理由退货。",
            key_points=["30 天内", "未拆封"],
            exceptions=["定制类商品不适用"],
            sources=["c99"],
            status=EntryStatus.PUBLISHED,
        ),
    ),
    (
        "B 新旧并存",
        "v1 说 7 天，v2 说 15 天，两条都是 published",
        WikiEntry(
            id="w-b-v2", title="质量问题退换", type=EntryType.RULE,
            definition="签收后 15 天内出现质量问题，可申请换新或退货。",
            key_points=["15 天内"],
            exceptions=[],
            sources=["c4"],
            status=EntryStatus.PUBLISHED,
            version=2,
        ),
    ),
    (
        "C 例外被吞",
        "原文写「已激活的数码产品不适用」，条目里 exceptions 是空的",
        WikiEntry(
            id="w-c", title="激活后的退货", type=EntryType.RULE,
            definition="已激活的数码产品可以申请退货。",
            key_points=["已激活可退"],
            exceptions=[],
            sources=["c2"],
            status=EntryStatus.PUBLISHED,
        ),
    ),
]


def format_ok(e: WikiEntry) -> tuple[bool, list[str]]:
    """最朴素的"格式检查"：字段齐不齐、长度够不够。很多团队就只做这一步。"""
    problems = []
    if not e.title:
        problems.append("缺标题")
    if len(e.definition) < 10:
        problems.append("定义太短")
    if not e.sources:
        problems.append("缺来源")
    return (not problems), problems


def source_exists(idx: Index, e: WikiEntry) -> tuple[bool, str]:
    """可溯源检查：sources 里的 chunk id 必须存在，且定义里的关键数字要能在原文里找到。"""
    ids = {c.id for c in idx.chunks}
    missing = [s for s in e.sources if s not in ids]
    if missing:
        return False, f"引用了不存在的 chunk：{missing}"
    text = "\n".join(c.text for c in idx.chunks if c.id in e.sources)
    nums = re.findall(r"\d+", e.definition)
    bad = [n for n in nums if n not in text]
    if bad:
        return False, f"定义里的数字 {bad} 在来源原文里找不到"
    return True, "来源可回溯"


def main() -> None:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=300))

    print("=" * 78)
    print("三条病条，先过'格式检查'")
    print("=" * 78)
    for tag, why, e in SICK:
        ok, problems = format_ok(e)
        print(f"  【{tag}】{'✅ 通过' if ok else '❌ ' + '、'.join(problems)}")
        print(f"     病情：{why}")

    print("\n" + "=" * 78)
    print("换成'可溯源检查'再看一遍")
    print("=" * 78)
    for tag, why, e in SICK:
        ok, detail = source_exists(idx, e)
        print(f"  【{tag}】{'✅ 通过' if ok else '❌ ' + detail}")

    print("\n" + "=" * 78)
    print("结论：格式检查拦不住任何一个真实故障")
    print("=" * 78)
    print("  · A 来源造假：sources 字段有值，但值是瞎写的 → 只有'回原文核对'能发现")
    print("  · B 新旧并存：两条条目各自都合法 → 只有'版本状态机'能发现")
    print("  · C 例外被吞：exceptions 为空在格式上完全合法 → 只有'和原文比对'能发现")

    print("\n" + "=" * 78)
    print("所以 wiki 的质量问题，本质是三个问题：")
    print("  1. 这条说的，原文真的这么说了吗？       → 24.10 / 本文件 step2")
    print("  2. 这条是当前有效版本吗？               → step3 的版本状态机")
    print("  3. 这条该有的例外，漏了吗？             → 体检清单（25.5）")
    print("=" * 78)

    # 顺手展示：库里有两条同主题的 published 条目时，检索会返回哪条
    store = WikiStore()
    base = WikiEntry(
        id="w-b-v1", title="质量问题退换", type=EntryType.RULE,
        definition="签收后 7 天内出现质量问题，可申请换新或退货。",
        key_points=["7 天内"], exceptions=[], sources=["c4"], status=EntryStatus.PUBLISHED, version=1,
    )
    store.upsert(base)
    store.upsert(SICK[1][2])
    print("\n  库里两条同主题条目，检索'质量问题几天内可以换新'：")
    from common.wiki import search

    for e, s in search(store, "质量问题几天内可以换新", top_k=3):
        print(f"    {s:.3f}  v{e.version}  {e.definition}")
    print("  ← 两条都返回，得分几乎一样。模型只能靠运气挑一条。")
    store.close()


if __name__ == "__main__":
    main()
