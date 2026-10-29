"""批量编码与缓存：批次大小对吞吐的影响，以及重复编码的浪费。

批次大小属于 encode_kwargs（LangChain 的 HuggingFaceEmbeddings 没有
embed_documents(batch_size=...) 这个参数），所以每种批次新建一个实例。
首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

import time

from langchain_huggingface import HuggingFaceEmbeddings

SMALL = "BAAI/bge-small-zh-v1.5"

TEMPLATES = [
    "质量问题退货，运费由商家承担。第 {} 条",
    "非质量问题退货，运费由买家承担。第 {} 条",
    "签收后 7 天内可申请无理由退货。第 {} 条",
    "发票可在订单页申请，开票时限 30 天。第 {} 条",
    "生鲜类商品不支持无理由退货。第 {} 条",
]

DOCS = [t.format(i) for i in range(12) for t in TEMPLATES]   # 60 条


def timed(fn, *args, **kwargs):
    t = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, (time.perf_counter() - t) * 1000


def build(batch_size: int) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=SMALL,
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch_size},
    )


def main() -> None:
    print(f"模型 {SMALL}，样本 {len(DOCS)} 条")

    print()
    print("=== 1. 批次大小（encode_kwargs['batch_size']）===")
    print(f"  {'batch_size':>10}{'耗时(ms)':>10}{'条/秒':>10}")
    for bs in [1, 8, 32, 64]:
        emb = build(bs)
        emb.embed_query("预热")                      # 排除首次前向的固定开销
        _, ms = timed(emb.embed_documents, DOCS)
        print(f"  {bs:>10}{ms:>10.0f}{len(DOCS) / (ms / 1000):>10.1f}")

    emb = build(32)
    q = "退货运费谁出"
    emb.embed_query(q)

    print()
    print("=== 2. 单条查询的固定开销 ===")
    _, first = timed(emb.embed_query, q)
    _, second = timed(emb.embed_query, q)
    print(f"  同一句查询连续两次：{first:.1f} ms / {second:.1f} ms")
    print("  编码本身的成本远小于一次模型调用的网络往返，"
          "所以在线查询阶段的瓶颈通常不在编码")

    print()
    print("=== 3. 重复编码的浪费 ===")
    batch = DOCS[:20]
    _, once = timed(emb.embed_documents, batch)
    _, twice = timed(emb.embed_documents, batch)
    cache: dict[str, list[float]] = {}

    def fill():
        for d, v in zip(batch, emb.embed_documents(batch)):
            cache[d] = v

    _, cold = timed(fill)
    _, warm = timed(lambda: [cache[d] for d in batch])
    print(f"  20 条算两遍：{once + twice:.0f} ms")
    print(f"  20 条算一遍 + 查缓存：{cold + warm:.0f} ms")
    print(f"  只查缓存：{warm:.2f} ms")
    print("  文档在库里的编码是一次性的；重复编码基本只发生在"
          "重新建索引与多实例各算一遍的时候")


if __name__ == "__main__":
    main()
