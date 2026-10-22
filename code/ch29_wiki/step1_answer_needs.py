"""第 29 章 step1：答案散在几个片段里，会怎样（离线，10 秒出结果）。

运行：
    python code/ch29_wiki/step1_answer_needs.py

上一级的痛点：无（这是起点）。
这一级做什么：证明"检索到相关片段"和"拿到一个完整答案"是两件事。

做法只有三步：
  1. 把`data/售后政策手册.md`切块
  2. 用最朴素的检索取出 top-K 片段
  3. 对每个问题，检查答案需要的要素（必须同时出现的几样东西）命中了几样
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

# (问题, 一个完整答案必须同时说到的要素)
QUESTIONS: list[tuple[str, list[str]]] = [
    ("无理由退货到底指什么？", ["7 天", "未拆封", "不影响二次销售"]),
    ("哪些商品不能无理由退货？", ["定制", "生鲜", "已激活"]),
    ("会员退货时优惠券怎么处理？", ["优惠券", "不返还"]),
    ("激活过的耳机能退吗？", ["已激活", "不适用"]),
    ("退货的运费谁出？", ["商家承担", "买家承担"]),
]


def covered(text: str, keys: list[str]) -> list[str]:
    return [k for k in keys if k in text]


def main() -> None:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=300))

    print("=" * 76)
    print("实验：检索到了，≠ 答得出来")
    print("=" * 76)
    print(f"文档 {len(DOC)} 字符 → 切成 {len(idx.chunks)} 块（按标题切，每块 ≤300 字）")
    print("每个问题取 top-3 片段，看'答案要素'凑齐了几样\n")

    total_keys = total_hits = 0
    incomplete = 0
    for q, keys in QUESTIONS:
        hits = idx.search(q, k=3)
        text = "\n".join(c.text for c, _ in hits)
        got = covered(text, keys)
        lack = [k for k in keys if k not in got]
        total_keys += len(keys)
        total_hits += len(got)
        if lack:
            incomplete += 1
        print(f"\n【{q}】")
        for c, s in hits:
            print(f"    {s:.2f}  {c.text.split(chr(10))[0][:40]}")
        print(f"    要素 {len(got)}/{len(keys)}：{('缺 ' + '、'.join(lack)) if lack else '齐全'}")

    print("\n" + "-" * 76)
    print(f"整体要素覆盖率：{total_hits}/{total_keys}（{total_hits / total_keys:.0%}）")
    print(f"要素不全的问题：{incomplete}/{len(QUESTIONS)}")

    print("\n" + "=" * 76)
    print("结论：失败不是因为'检索不准'，而是因为'答案本来就不在一块里'")
    print("=" * 76)
    print("  取回 top-3 之后，我们手里是一堆**并列的片段**，而不是一条**结论**：")
    print("    · 片段 A 讲条件（7 天 / 未拆封）")
    print("    · 片段 B 讲例外（定制、生鲜、已激活）")
    print("    · 片段 C 讲运费或优惠券")
    print("  这些片段谁主谁次、哪句是定义、哪句是例外，没有人替你说清楚。")
    print()
    print("  交给模型去拼，它会拼，但不稳定：片段顺序一变、哪一句被截断，")
    print("  答案就会漏掉例外——这正是第 39 章讲过的 lost in the middle。")

    print("\n" + "=" * 76)
    print("所以我们要问的是：")
    print("  能不能在'检索'之前，先把这件事**整理成一条固定的陈述**？")
    print("=" * 76)
    print("  下一级：给每个知识点定义一个固定的'形状'（四个字段），")
    print("  让'这条知识到底说什么'变成一个可以直接读的对象。")


if __name__ == "__main__":
    main()
