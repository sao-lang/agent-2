"""第 25 章 step3：状态机 + 版本 + 体检，一次跑完（离线）。

运行：
    python code/ch25_wiki_ops/step3_lifecycle.py

上一级的痛点：抽取通过校验，但"旧的那条怎么办""被举报了怎么办"没人管。

这一级做什么：用 `common/wiki.py` 的完整实现走一遍生命周期：
  ① 草稿 → 发布
  ② 修订：v1 published + v2 reviewing 同时存在，检索该返回谁
  ③ 审核通过：v1 自动 outdated，v2 变成唯一有效版本
  ④ 质量信号：有用票 / 过时举报如何压排名
  ⑤ 体检：五类清单，每周跑一次
"""
from __future__ import annotations

import sys
import time
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
    score_entry,
    search,
)


def add(store: WikiStore, e: WikiEntry) -> WikiEntry:
    store.upsert(e)
    return e


def health_check(store: WikiStore, tenant_id: str = "default") -> dict[str, list[str]]:
    """体检：五类清单。每周跑一次，输出的是"待办"，不是"报表"。"""
    now = time.time()
    pub = store.list(status=EntryStatus.PUBLISHED, tenant_id=tenant_id)
    return {
        "无来源": [e.id for e in pub if not e.sources],
        "无例外": [e.id for e in pub if not e.exceptions],
        "90 天未更新": [e.id for e in pub if (now - e.updated_at) / 86400 > 90],
        "被举报≥3": [e.id for e in pub if e.outdated_reports >= 3],
        "从未被用过": [e.id for e in pub if e.hit_count == 0],
    }


def main() -> None:
    store = WikiStore()

    print("=" * 78)
    print("① 草稿 → 发布")
    print("=" * 78)
    v1 = add(
        store,
        WikiEntry(
            id="w-refund", title="无理由退货", type=EntryType.RULE,
            definition="签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。",
            key_points=["7 天内", "未拆封", "不影响二次销售"],
            exceptions=["定制类商品不适用", "已激活的数码产品不适用"],
            sources=["c2"],
            status=EntryStatus.DRAFT,
        ),
    )
    print(f"  新建：{v1.id} [{v1.status.value}]")
    publish(store, v1.id, reviewer="policy-owner")
    print(f"  审核后：{store.get(v1.id).status.value}（reviewers={store.get(v1.id).reviewers}）")

    print("\n" + "=" * 78)
    print("② 修订：数字从 7 变成 15")
    print("=" * 78)
    sig = conflict(v1, "签收后 15 天内，商品未拆封且不影响二次销售的，可申请无理由退货。")
    print(f"  冲突信号：{sig}")
    r = revise(
        store, v1.id,
        "签收后 15 天内，商品未拆封且不影响二次销售的，可申请无理由退货。",
        reviewer="policy-owner",
        auto_approve=True,          # 即使要求自动批准，有了冲突也不会批
    )
    print(f"  修订结果：ok={r['ok']}  新 id={r['new_id']}  状态={r['status']}  自动批准={r['auto_approved']}")
    print("\n  当前所有版本：")
    for e in store.list(include_superseded=True):
        print(f"    v{e.version} [{e.status.value:<9}] {e.definition[:26]}…  superseded_by={e.superseded_by or '-'}")

    print("\n  此时检索'无理由退货几天内'：")
    for e, s in search(store, "无理由退货几天内", top_k=3):
        print(f"    {s:.3f}  v{e.version} {e.status.value}  {e.definition[:28]}…")
    print("  ← v2 还在 reviewing，检索只返回 v1。**审核期间旧版本继续生效**，")
    print("     否则审核的 2 小时里，客服系统会没有可用答案。")

    print("\n" + "=" * 78)
    print("③ 审核通过：v1 自动 obsolete")
    print("=" * 78)
    publish(store, r["new_id"], reviewer="legal-owner")
    for e in store.list(include_superseded=True):
        print(f"    v{e.version} [{e.status.value:<9}] superseded_by={e.superseded_by or '-'}")
    print("\n  检索再跑一次：")
    for e, s in search(store, "无理由退货几天内", top_k=3):
        print(f"    {s:.3f}  v{e.version} {e.status.value}  {e.definition[:28]}…")
    print("  ← 现在只有 v2。旧版本不是被删掉，而是被标成 outdated：")
    print("     '上个月客户被告知 7 天' 这件事，还能从库里查到。")

    print("\n" + "=" * 78)
    print("④ 质量信号怎么压排名")
    print("=" * 78)
    add(store, WikiEntry(
        id="w-ship", title="运费承担", type=EntryType.RULE,
        definition="非人为质量问题，往返运费由商家承担。",
        key_points=["商家承担"], exceptions=[], sources=["c6"],
        status=EntryStatus.PUBLISHED, hit_count=40, helpful_votes=12,
    ))
    add(store, WikiEntry(
        id="w-ship-old", title="运费承担（旧版）", type=EntryType.RULE,
        definition="运费由商家承担，一律包邮。",
        key_points=["商家承担"], exceptions=[], sources=["c6"],
        status=EntryStatus.PUBLISHED, outdated_reports=8,
    ))
    print(f"  {'条目':<18}{'命中':>6}{'有用':>6}{'举报':>6}{'得分':>8}")
    print("  " + "-" * 46)
    for e in store.list(status=EntryStatus.PUBLISHED):
        if "运费" in e.title:
            print(f"  {e.title:<18}{e.hit_count:>6}{e.helpful_votes:>6}{e.outdated_reports:>6}"
                  f"{score_entry(e, '运费谁承担'):>8.3f}")
    print("\n  ← 同样相关，被举报 8 次的条目分数低了一个量级。")
    print("     这就是 wiki 相对向量库的核心差异：**知识质量能参与排序**。")

    print("\n" + "=" * 78)
    print("⑤ 体检清单（每周跑）")
    print("=" * 78)
    report = health_check(store)
    for k, v in report.items():
        print(f"  {k:<12}{len(v):>3}   {v or '—'}")
    print("\n  ← 这份清单本身就是'下周该干什么'：")
    print("     · 无来源 → 补来源或下架")
    print("     · 无例外 → 人复查（可能真没有，也可能漏了）")
    print("     · 90 天未更新 → 找业务确认政策是否变了")
    print("     · 被举报≥3 → 进重写队列")
    print("     · 从未被用过 → 要么写错地方了，要么这条根本不需要")

    store.close()


if __name__ == "__main__":
    main()
