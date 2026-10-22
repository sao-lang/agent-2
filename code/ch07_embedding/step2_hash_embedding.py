"""第 7 章 step2：从词袋到嵌入——为什么"哈希嵌入"能救一半（离线）。

运行：
    python code/ch07_embedding/step2_hash_embedding.py

上一级的痛点（step1）：词袋对"不想要了能退吗"打分 0.000——
                     完全找不到任何文档，因为它一个词都没匹配上。

这一级做什么：用**哈希嵌入**（把字/词组映射到一个固定维度的向量）解决一部分问题，
             并诚实地说清它解决了什么、没解决什么。

  解决了：字级别的相似（"退货"和"退货政策"共享"退""货"两个字）
  没解决：真正的同义词（"退钱" vs "退款" 只共享"退"）

这一级的意义：**让你看清"嵌入"不神秘——它就是"换一种方式把文本变成数字"**。
             真实嵌入模型（text-embedding-3 / bge）做的事一样，
             只是它用几十亿参数学到了"哪些字常常一起出现"。
"""
from __future__ import annotations

import math

DIM = 128  # 故意用小维度，方便观察"碰撞"


def hash_embed(text: str, dim: int = DIM, ngram: int = 2) -> list[float]:
    """字符 n-gram 哈希嵌入。

    做法：
      ① 把文本切成 n-gram（"退货政策" → 退货/货政/政策）
      ② 每个 n-gram 哈希到一个维度下标
      ③ 该维度 +1
      ④ 归一化

    这正是本书 `common/retrieval.py` 里 `hash_embed` 的思路（那里用 numpy）。
    它的价值：**离线、确定、不需要 API key，但已经能算"字面相似"**。
    """
    vec = [0.0] * dim
    text = text.replace(" ", "")
    grams = [text[i : i + ngram] for i in range(max(1, len(text) - ngram + 1))]
    for g in grams:
        # 稳定哈希：同样的输入永远得到同样的下标（不能用 Python 的 hash，因为每次进程不同）
        h = 0
        for ch in g:
            h = (h * 131 + ord(ch)) % 1_000_003
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


DOCS = [
    "退货政策：签收后七天内可申请无理由退货",
    "退货规则：商品需保持完好且不影响二次销售",
    "换货流程：质量问题可在十五天内换新",
    "物流时效：一般三到五个工作日送达",
    "退款到账：审核通过后三到七个工作日到账",
]

QUERIES = [
    ("退货政策", "字面高度重合"),
    ("退货规则", "字面高度重合"),
    ("不想要了能退吗", "**换了说法**：字面只共享 '退'"),
    ("钱什么时候到账", "**换了说法**：字面共享 '到账'"),
    ("东西坏了能换吗", "**换了说法**：字面共享 '换'"),
]


def main() -> None:
    print("=" * 88)
    print("哈希嵌入：把文本变成 128 维向量（字符 2-gram）")
    print("=" * 88)
    print(f"维度：{DIM}（真实嵌入模型是 768 / 1024 / 1536）")
    print("方法：切成字符 2-gram → 哈希到维度 → 计数 → 归一化\n")

    # 演示一个文本怎么变成向量
    demo = "退货政策"
    vec = hash_embed(demo)
    nz = [(i, round(v, 3)) for i, v in enumerate(vec) if v]
    print(f"「{demo}」的向量（非零维度）：")
    print(f"  {nz}")
    print(f"  非零维度数：{len(nz)}  ← 稀疏向量（大部分是 0）")
    print(f"  长度（L2 范数）：{math.sqrt(sum(x * x for x in vec)):.3f}  ← 归一化后恒为 1")

    print("\n" + "=" * 88)
    print("检索效果：5 个查询")
    print("=" * 88)
    doc_vecs = [hash_embed(d) for d in DOCS]

    for q, note in QUERIES:
        qv = hash_embed(q)
        scores = sorted(
            ((cosine(qv, dv), d) for dv, d in zip(doc_vecs, DOCS)), reverse=True
        )
        print(f"\n查询：「{q}」   （{note}）")
        for s, d in scores[:2]:
            bar = "█" * int(s * 30)
            print(f"  {s:.3f} {bar:<30} {d[:26]}")

    print("\n" + "=" * 88)
    print("对比词袋 vs 哈希嵌入")
    print("=" * 88)
    print(f"{'查询':<18}{'词袋最高分':>12}{'哈希嵌入最高分':>14}   改善")
    print("-" * 88)

    from step1_what_is_vector import bag_of_words, cosine as cos2

    # 词袋用切好的词
    tok_docs = [d.replace("：", " ").replace("，", " ") for d in DOCS]
    vocab = sorted({c for d in tok_docs for c in d})
    for q, _ in QUERIES:
        q_tokens = " ".join(q)
        bow_scores = max(
            cos2(bag_of_words(q_tokens, vocab), bag_of_words(d, vocab)) for d in tok_docs
        )
        hash_scores = max(cosine(hash_embed(q), dv) for dv in doc_vecs)
        improve = "✅" if hash_scores > bow_scores + 0.1 else ("─" if hash_scores > bow_scores else "❌")
        print(f"{q:<18}{bow_scores:>12.3f}{hash_scores:>14.3f}   {improve}")
    print("-" * 88)

    print("\n" + "=" * 88)
    print("诚实地说：哈希嵌入解决了什么、没解决什么")
    print("=" * 88)
    solved = [
        ("'退货政策' vs '退货规则'", "共享 '退货' 两个字 → 相似度 > 0.3"),
        ("'钱什么时候到账' vs '退款到账…'", "共享 '到账' → 能召回"),
        ("'东西坏了能换吗' vs '换货流程…'", "共享 '换' → 能召回（但排名不高）"),
    ]
    unsolved = [
        ("'退钱' vs '退款'", "只共享 '退' 一个字，相似度很低"),
        ("'不想要了' vs '无理由退货'", "**零字面重合** → 完全找不到"),
        ("'怎么把钱拿回来' vs '退款'", "换成口语 → 失效"),
    ]
    print("  ✅ 解决了（字面有重叠的换说法）：")
    for a, b in solved:
        print(f"     {a:<34}{b}")
    print("\n  ❌ 没解决（真正的同义词 / 口语化表达）：")
    for a, b in unsolved:
        print(f"     {a:<34}{b}")
    print()
    print("  **根本原因：哈希嵌入不知道'退钱'和'退款'是一个意思。**")
    print("  它只知道'这两个字长什么样'。要懂意思，必须有**语义嵌入模型**（step3）。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  · 嵌入的本质：**把文本变成向量，让'意思接近'变成'距离接近'**。")
    print("  · 哈希嵌入是'字面级'的嵌入——便宜、离线、确定，但不懂同义词。")
    print("  · 真实嵌入模型（text-embedding-3 / bge / qwen-embedding）")
    print("    用几十亿参数学到了'哪些词常常出现在相似的上下文里'，所以它懂'退钱=退款'。")
    print("  · **但两者的用法完全一样**：算余弦、取 top-k。")
    print("    所以本章后面的所有代码，换成真实嵌入模型就能直接跑。")

    assert hash_embed("退货") != hash_embed("退款"), "不同文本必须有不同向量"
    assert hash_embed("退货") == hash_embed("退货"), "同样文本必须得到同样向量（确定性）"


if __name__ == "__main__":
    main()
