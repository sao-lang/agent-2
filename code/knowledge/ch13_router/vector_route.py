"""用真实嵌入做意图质心路由，与关键词打分对照。

首次运行需下载 bge-small-zh-v1.5（约 95 MB）：
    $env:HF_ENDPOINT = "https://hf-mirror.com"
    $env:HF_HUB_DISABLE_SYMLINKS = "1"     # Windows 无符号链接权限时
模型只用于演示"质心 + 阈值"这套判据，分数不是概率。
"""

from __future__ import annotations

import math

from langchain_huggingface import HuggingFaceEmbeddings

MODEL = "BAAI/bge-small-zh-v1.5"

# 每个意图给三到四条种子说法，质心是它们的嵌入均值
INTENTS: dict[str, list[str]] = {
    "refund": ["我想退货", "这个能退吗", "退款怎么还没到账", "七天无理由怎么算"],
    "tracking": ["我的包裹到哪了", "什么时候能送到", "物流三天没动了"],
    "warranty": ["保修多久", "这个坏了能修吗", "质保范围包括什么"],
}

# 前三条与种子说法没有字面重合，第四、五条故意不在三个意图里
QUERIES = [
    "我买的东西还没到",
    "刚下的单什么时候发货",
    "耳机用了半年就坏了怎么办",
    "这个耳机保修几年",
    "发票怎么开",
]

KEYWORDS = {
    "refund": ["退货", "退款", "能退", "退吗"],
    "tracking": ["物流", "到哪", "送到", "包裹", "发货"],
    "warranty": ["保修", "质保", "坏了"],
}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def keyword_scores(text: str) -> dict[str, float]:
    """关键词基线：命中一个词加 0.45，封顶 0.99。"""
    return {label: min(0.99, sum(1 for w in words if w in text) * 0.45)
            for label, words in KEYWORDS.items()}


def main() -> None:
    emb = HuggingFaceEmbeddings(
        model_name=MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )

    labels = list(INTENTS)
    seeds = [s for label in labels for s in INTENTS[label]]
    seed_vecs = emb.embed_documents(seeds)

    centroids: dict[str, list[float]] = {}
    pos = 0
    for label in labels:
        block = seed_vecs[pos:pos + len(INTENTS[label])]
        pos += len(INTENTS[label])
        dim = len(block[0])
        centroids[label] = [sum(vec[d] for vec in block) / len(block) for d in range(dim)]

    print(f"模型 {MODEL}，维度 {len(centroids[labels[0]])}，意图 {len(labels)} 个")
    print()
    print(f"  {'查询':<22}" + "".join(f"{l:>10}" for l in labels) + "   最高分")
    for q in QUERIES:
        v = emb.embed_query(q)
        scores = {label: cosine(v, centroids[label]) for label in labels}
        top = max(scores, key=scores.get)
        row = "".join(f"{scores[l]:>10.3f}" for l in labels)
        print(f"  {q:<22}{row}   {top} {scores[top]:.3f}")

    print()
    print("=== 关键词基线：同一批查询 ===")
    for q in QUERIES:
        kw = keyword_scores(q)
        top = max(kw, key=kw.get)
        print(f"  {q:<22}{top:<10}{kw[top]:.2f}   "
              f"（{len([1 for ws in KEYWORDS.values() for w in ws if w in q])} 个词命中）")

    print()
    print("=== 阈值扫描：低于阈值即退出这一层 ===")
    for t in [0.50, 0.55, 0.60, 0.65]:
        out = []
        for q in QUERIES:
            v = emb.embed_query(q)
            best = max(cosine(v, centroids[label]) for label in labels)
            out.append(f"{best:.2f}{'进' if best >= t else '退'}")
        print(f"  阈值 {t:.2f}  " + "  ".join(out))


if __name__ == "__main__":
    main()
