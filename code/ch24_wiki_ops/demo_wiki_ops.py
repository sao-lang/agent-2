"""第 24 章示例：wiki 的生成、矛盾检测、版本与质量治理（不需要 API）。

运行：
    python code/ch24_wiki_ops/demo_wiki_ops.py

五个治理环节：
  1. 生成（规则 + 模型两条路）
  2. 矛盾检测（极性翻转 / 数字不符）
  3. 版本修订（旧的标 outdated，不是删掉）
  4. 过时举报（用户/系统反馈）
  5. 覆盖率与质量指标（能对业务方汇报）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.wiki import (  # noqa: E402
    EntryStatus,
    EntryType,
    WikiEntry,
    WikiStore,
    conflict,
    publish,
    revise,
    search,
)


def seed(store: WikiStore) -> str:
    e = WikiEntry(
        id="w-refund",
        title="无理由退货",
        type=EntryType.RULE,
        definition="签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。",
        key_points=["7 天内", "未拆封", "不影响二次销售"],
        exceptions=["定制类商品不适用", "生鲜类商品不适用", "已激活的数码产品不适用"],
        sources=["c2"],
        status=EntryStatus.DRAFT,
    )
    store.upsert(e)
    publish(store, e.id, reviewer="policy-owner")
    return e.id


def main() -> None:
    store = WikiStore()
    entry_id = seed(store)

    print("=" * 76)
    print("① 生成：一个合格条目长什么样")
    print("=" * 76)
    e = store.get(entry_id)
    for line in e.render().split("\n"):
        print(f"  {line}")
    print("\n  四个字段缺一不可：")
    print("    · definition：一句话说清是什么（可独立理解）")
    print("    · key_points：可核对的事实（含数字）")
    print("    · exceptions：**主动找出来的例外**（最容易被漏）")
    print("    · sources：能指回的原文（可溯源）")

    print("\n" + "=" * 76)
    print("② 矛盾检测：三种常见情况")
    print("=" * 76)
    cases = [
        ("数字变化（7 天 → 15 天）", "签收后 15 天内，商品未拆封且不影响二次销售的，可申请无理由退货。"),
        ("极性翻转（可申请 → 不可申请）", "无理由退货不可申请，所有商品均不支持退货。"),
        ("新增例外", "签收后 7 天内可申请无理由退货，但食品类商品不适用。"),
    ]
    for label, new_def in cases:
        sig = conflict(e, new_def)
        flag = "⚠️ 需人工审核" if sig["needs_review"] else "✅ 可自动通过"
        print(f"\n  【{label}】{flag}")
        print(f"    极性翻转：{sig['polarity_flip']}    数字不符：{sig['number_mismatch']}")
        print(f"    旧数字：{sig['old_numbers']}  新数字：{sig['new_numbers']}")
        print(f"    主题相似度：{sig['topic_similarity']}  评分：{sig['score']}")

    print("\n  👉 '数字变化'和'极性翻转'都必须人工审核：")
    print("     7 天变 15 天，可能是一次政策调整，也可能是模型抄错了。")
    print("     自动通过 = 把这种错误直接发布出去。")

    print("\n" + "=" * 76)
    print("③ 修订：版本 +1，旧的标 outdated（不是删除）")
    print("=" * 76)
    r = revise(
        store, entry_id,
        "签收后 10 天内，商品未拆封且不影响二次销售的，可申请无理由退货。",
        reviewer="policy-owner",
        auto_approve=True,
    )
    print(f"  结果：ok={r['ok']}  新 id={r['new_id']}")
    print(f"  状态：{r['status']}（自动批准={r['auto_approved']}）")
    print(f"  冲突：{r['conflict']}")
    print("\n  当前所有版本：")
    for item in store.list(include_superseded=True):
        mark = "← 当前" if item.superseded_by is None else f"→ 被 {item.superseded_by} 取代"
        print(f"    v{item.version}  [{item.status.value:<9}] {item.definition[:30]}...  {mark}")

    print("\n  👉 为什么软删除：你要能回答'上个月客户被告知 7 天，为什么现在变成 10 天'。")

    print("\n" + "=" * 76)
    print("④ 质量信号：哪些条目该被淘汰/重写")
    print("=" * 76)
    # 造几条质量不同的条目
    extras = [
        ("w-a", "运费承担", "非人为质量问题，往返运费由商家承担。", 0, 0),
        ("w-b", "价格保护", "签收后 15 天内降价可申请价保。", 12, 0),
        ("w-c", "已过期条款", "（过时）签收后 3 天内可退货。", 3, 8),   # 被多次举报
    ]
    for eid, title, definition, votes, reports in extras:
        en = WikiEntry(
            id=eid, title=title, type=EntryType.RULE, definition=definition,
            key_points=[], exceptions=[], sources=["c3"],
            status=EntryStatus.PUBLISHED, helpful_votes=votes, outdated_reports=reports,
        )
        store.upsert(en)

    print(f"  {'条目':<14}{'有用票':>8}{'过时举报':>10}{'需重写':>8}")
    print("  " + "-" * 44)
    for en in store.list(status=EntryStatus.PUBLISHED):
        need = "是" if en.outdated_reports >= 3 else "否"
        print(f"  {en.title:<14}{en.helpful_votes:>8}{en.outdated_reports:>10}{need:>8}")

    print("\n  👉 过时举报 >= 3 的条目应该进入 '待重写' 队列。")
    print("     这是 wiki 相对纯 RAG 的核心优势：**知识质量是可度量的。**")

    print("\n" + "=" * 76)
    print("⑤ 检索：质量信号如何影响排序")
    print("=" * 76)
    q = "运费谁承担"
    print(f"  查询：{q}")
    for en, s in search(store, q, top_k=4):
        print(f"    {s:.4f}  {en.title:<12}有用票={en.helpful_votes} 举报={en.outdated_reports}")
    print("\n  → 被打过 8 次'过时'的条目排名被压低了。")
    print("     这就是把'知识质量'接入检索的意义：**坏知识不该和好知识竞争。**")

    print("\n" + "=" * 76)
    print("⑥ 覆盖率指标（对业务方汇报用）")
    print("=" * 76)
    all_e = store.list(include_superseded=True)
    published = store.list(status=EntryStatus.PUBLISHED)
    with_src = [x for x in published if x.sources]
    with_exc = [x for x in published if x.exceptions]
    print(f"  条目总数：{len(all_e)}（当前有效 {len(published)}）")
    print(f"  有来源的比例：{len(with_src) / max(len(published), 1):.0%}   ← 可溯源率")
    print(f"  有例外说明的比例：{len(with_exc) / max(len(published), 1):.0%}   ← 例外覆盖率")
    print("\n  这两个指标比'条目数'重要得多：")
    print("    · 190 条没来源的条目 < 20 条有来源的条目")
    print("    · 例外覆盖率低的 wiki，会把'通常情况'当成'全部情况'，直接导致错答")

    store.close()


if __name__ == "__main__":
    main()
