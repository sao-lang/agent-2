"""第 31 章示例：三种分块策略的召回率对比（不需要 API）。

运行：
    python code/ch11_chunking/demo_chunking.py

这是"分块策略直接决定召回率"的实证：
同一份文档、同一批问题、同一个嵌入，只改分块方式，recall@k 差异明显。

⚠️ 这里用的是哈希嵌入（离线可跑），它的语义能力弱于真嵌入模型，
   所以绝对值会偏低；但**策略之间的相对差异**是可迁移的结论。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import (  # noqa: E402
    Index,
    hash_embed,
    split_by_heading,
    split_fixed,
    split_parent_child,
    split_semantic,
)

DOC = (Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md").read_text(encoding="utf-8")

# 每个问题标注"正确答案应该落在哪个关键词上"
CASES = [
    ("无理由退货几天内可以申请？", "7 天"),
    ("蓝牙耳机右耳有电流声怎么办？", "编解码"),
    ("换新流程要多久？", "5 到 7 个工作日"),
    ("运费谁承担？", "往返运费由商家承担"),
    ("怎么转人工客服？", "转人工"),
    ("会员有什么优惠？", "满 300 减 30"),
    ("价格保护几天内有效？", "15 天"),
    ("发票多久能开出来？", "7 个工作日"),
]


def build(strategy: str) -> Index:
    idx = Index(embed=hash_embed)
    if strategy.startswith("fixed-"):
        size = int(strategy.split("-")[1])
        idx.add(split_fixed(DOC, size=size, overlap=max(30, size // 6)))
    elif strategy == "heading":
        idx.add(split_by_heading(DOC, max_chars=500))
    elif strategy == "semantic":
        idx.add(split_semantic(DOC, max_chars=400, similarity_threshold=0.12))
    elif strategy == "parent-child":
        pairs = split_parent_child(DOC, parent_size=900, child_size=250)
        idx.add([c for c, _ in pairs], [{"parent": p} for _, p in pairs])
    else:
        raise ValueError(strategy)
    return idx


def recall_at(idx: Index, k: int = 3) -> tuple[float, list[str]]:
    """recall@k：正确答案是否出现在前 k 条里。

    为什么不用精确匹配整段文本？因为分块方式变了，文本一定不同。
    用「关键词是否出现在命中块里」作为命中判据，才对所有策略公平。
    """
    hits = 0
    missed = []
    for q, keyword in CASES:
        results = idx.search(q, k=k)
        if any(keyword in c.text for c, _ in results):
            hits += 1
        else:
            missed.append(q)
    return hits / len(CASES), missed


def main() -> None:
    print(f"文档长度：{len(DOC)} 字符    问题数：{len(CASES)}\n")

    strategies = ["fixed-200", "fixed-500", "fixed-1000", "heading", "semantic", "parent-child"]

    print(f"{'策略':<14}{'块数':>6}{'平均长度':>10}{'recall@3':>10}{'recall@1':>10}   未命中(@3)")
    print("-" * 88)
    for s in strategies:
        idx = build(s)
        avg_len = sum(len(c.text) for c in idx.chunks) / max(len(idx.chunks), 1)
        r3, missed3 = recall_at(idx, 3)
        r1, _ = recall_at(idx, 1)
        print(
            f"{s:<14}{len(idx.chunks):>6}{avg_len:>10.0f}{r3:>9.0%}{r1:>10.0%}   "
            f"{'; '.join(m[:12] for m in missed3) or '—'}"
        )

    print("\n" + "=" * 88)
    print("怎么读这张表")
    print("=" * 88)
    print("  · recall@3 看「有没有找到」，recall@1 看「排得准不准」")
    print("  · 块太大（1000）：一块塞多个主题，recall@1 会掉（命中但排在第 2-3 位）")
    print("  · 块太小（semantic 这里只有 23 字/块）：句子被切碎，语义残缺，召回崩掉")
    print("  · 按标题切：天然对齐主题边界，通常优于定长")
    print("  · 父子分块：小块检索（准）+ 大块生成（全），生产首选")
    print("\n  ⚠️ 这份文档只有 889 字、8 个问题，样本太小，recall@3 容易打满。")
    print("     请把 data/ 换成你自己的文档（>5 万字、50+ 问题），结论才可靠。")
    print("     另外这里用哈希嵌入（离线可跑），换成真嵌入模型后绝对值会明显上升。")

    print("\n" + "=" * 88)
    print("演示：父块如何提升答案完整性")
    print("=" * 88)
    pc = build("parent-child")
    q = "蓝牙耳机右耳有电流声怎么办？"
    for chunk, score in pc.search(q, k=1):
        print(f"  命中 child（{len(chunk.text)} 字，score={score:.3f}）：")
        print(f"    {chunk.text[:80]}...")
        print(f"  返回给模型的 parent（{len(chunk.meta['parent'])} 字）：")
        print(f"    {chunk.meta['parent'][:120]}...")
    print("\n  👉 child 负责「找得准」，parent 负责「答得全」。只存 child 会丢上下文。")


if __name__ == "__main__":
    main()
