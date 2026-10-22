"""第 24 章示例：纯向量 RAG vs 有 wiki 的知识层（不需要 API）。

运行：
    python code/ch24_wiki/demo_wiki_vs_rag.py

`step1~step3` 证明了"检索到 ≠ 答得出"，并给出了条目优先的混合方案。
这个 demo 换成另一组问题，看**同一份语料上，两种知识层各自给了什么**：
  A. 定义类：向量能召回片段，但答不出"是什么"
  B. 口径类：需要版本，向量给不出"哪版是最新"
  C. 例外类：向量几乎必然漏掉（例外通常只有一句话，藏在角落）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402
from common.wiki import (  # noqa: E402
    EntryStatus,
    EntryType,
    WikiStore,
    extract_entry_rule,
    publish,
    search,
)

DOC = (Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md").read_text(encoding="utf-8")

QUESTIONS = [
    ("A 定义类", "无理由退货到底指什么？", ["7 天", "未拆封", "不影响二次销售"]),
    ("B 口径类", "会员退货时优惠券怎么处理？", ["不返还"]),
    ("C 例外类", "哪些商品不能无理由退货？", ["定制", "生鲜", "已激活"]),
]


def build_rag() -> Index:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=300))
    return idx


def build_wiki() -> WikiStore:
    store = WikiStore()
    idx = build_rag()

    # 用规则抽取把相关片段整理成条目（离线可跑）
    seeds = [
        ("无理由退货", "1.1 无理由退货"),
        ("质量问题退换", "1.2 质量问题退换"),
        ("运费承担", "1.3 运费承担"),
        ("会员权益与退货", "4.1 会员权益"),
        ("蓝牙耳机故障", "2.1 常见故障现象"),
    ]
    for title, heading in seeds:
        chunks = [c.text for c in idx.chunks if heading in c.text]
        if not chunks:
            continue
        e = extract_entry_rule(chunks, title, EntryType.RULE)
        e.sources = [c.id for c in idx.chunks if heading in c.text]
        store.upsert(e)
        publish(store, e.id, reviewer="author")
    return store


def check(text: str, keys: list[str]) -> tuple[int, list[str]]:
    hit = [k for k in keys if k in text]
    return len(hit), [k for k in keys if k not in text]


def main() -> None:
    idx = build_rag()
    store = build_wiki()

    print(f"RAG 片段：{len(idx.chunks)} 块")
    print(f"Wiki 条目：{len(store.list(status=EntryStatus.PUBLISHED))} 条（已发布）\n")

    print("=" * 78)
    print("对比：同一批问题，两种知识层能提供什么")
    print("=" * 78)

    for tag, q, keys in QUESTIONS:
        print(f"\n【{tag}】{q}")

        # ---- 纯 RAG ----
        rag_hits = idx.search(q, k=3)
        rag_text = "\n".join(c.text for c, _ in rag_hits)
        n_rag, miss_rag = check(rag_text, keys)
        print(f"  纯向量 top-3（{sum(len(c.text) for c, _ in rag_hits)} 字）：")
        for c, s in rag_hits:
            print(f"    {s:.2f}  {c.text.split(chr(10))[0][:34]}")
        print(f"    关键信息覆盖：{n_rag}/{len(keys)}  缺：{miss_rag or '—'}")

        # ---- Wiki ----
        w_hits = search(store, q, top_k=2)
        w_text = "\n".join(e.render() for e, _ in w_hits)
        n_w, miss_w = check(w_text, keys)
        print(f"  Wiki 条目 top-2（{sum(len(e.render()) for e, _ in w_hits)} 字）：")
        for e, s in w_hits:
            print(f"    {s:.2f}  {e.title}（{len(e.key_points)} 要点 / {len(e.exceptions)} 例外）")
        print(f"    关键信息覆盖：{n_w}/{len(keys)}  缺：{miss_w or '—'}")

    print("\n" + "=" * 78)
    print("结论：wiki 到底解决了什么")
    print("=" * 78)
    print("  1. **定义类**：向量给的是片段，wiki 给的是'这一条是什么'的完整表述")
    print("  2. **口径类**：wiki 有版本和状态（published/outdated），向量没有")
    print("  3. **例外类**：例外通常只有一句话，藏在段末——")
    print("     wiki 会用「## 例外」把它结构化出来，模型的注意力不会被稀释")
    print("\n  更重要的：**wiki 的每一条结论都能指回来源**（sources 字段）。")
    print("  这是纯向量 RAG 做不到的：它只能给你'相似的片段'，")

    print("\n" + "=" * 78)
    print("看一个真实条目长什么样")
    print("=" * 78)
    top = search(store, "哪些商品不能无理由退货", top_k=1)
    if top:
        e, s = top[0]
        print(f"  （得分 {s:.3f}）")
        for line in e.render().split("\n"):
            print(f"  {line}")

    print("\n" + "=" * 78)
    print("⚠️ 诚实说明")
    print("=" * 78)
    print("  · 这里用规则抽取生成条目，质量远不如模型抽取或人工撰写")
    print("  · 语料只有 889 字，覆盖度有限")
    print("  · 真实的 wiki 需要：模型抽取 → 人工审核 → 持续维护（见第 24 章）")
    print("  · wiki 不是替代 RAG，而是**在 RAG 之上加一层沉淀**")

    store.close()


if __name__ == "__main__":
    main()
