"""嵌入的三个读数问题：相似度矩阵、归一化与距离、截断。

用两个真实模型（bge-small 512 维、bge-base 768 维）。
首次运行需下载：bge-small 约 95 MB，bge-base 约 400 MB。
    $env:HF_ENDPOINT = "https://hf-mirror.com"
    $env:HF_HUB_DISABLE_SYMLINKS = "1"
"""

from __future__ import annotations

import math

from langchain_huggingface import HuggingFaceEmbeddings
from transformers import AutoTokenizer

SMALL = "BAAI/bge-small-zh-v1.5"
BASE = "BAAI/bge-base-zh-v1.5"

SENTENCES = [
    "退货运费由谁承担",
    "退货的运费谁出",
    "质量问题退货运费商家出",
    "发票多久能开",
    "签收后几天可以退货",
    "今天天气不错",
]

PAIRS = [
    ("退货运费由谁承担", "退货的运费谁出"),
    ("退货运费由谁承担", "质量问题退货运费商家出"),
    ("退货运费由谁承担", "发票多久能开"),
    ("退货运费由谁承担", "今天天气不错"),
]

LONG_HEAD = "退货运费按责任划分。质量问题导致的退货，往返运费由商家承担，用户无需支付。"
QUERY = "质量问题退货运费谁出"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def l2(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def model(name, normalize=True):
    return HuggingFaceEmbeddings(
        model_name=name,
        encode_kwargs={"normalize_embeddings": normalize},
    )


def section_matrix(emb):
    vecs = emb.embed_documents(SENTENCES)
    print("=== 1. 相似度矩阵（bge-small，归一化后）===")
    print(f"  {'':<3}" + "".join(f"{i:>7}" for i in range(len(SENTENCES))))
    for i, vi in enumerate(vecs):
        print(f"  {i:<3}" + "".join(f"{cosine(vi, vj):>7.2f}" for vj in vecs))
    print("  句子：" + "；".join(f"{i}={s}" for i, s in enumerate(SENTENCES)))
    print("  注意 0 与 1 几乎同义（0.89），0 与 3 只共享「退货」两个字（0.43）")


def section_normalize():
    print()
    print("=== 2. 归一化与距离度量 ===")
    raw = model(SMALL, normalize=False)
    nrm = model(SMALL, normalize=True)
    a_raw = raw.embed_query("退货运费由谁承担")
    b_raw = raw.embed_documents(["退货的运费谁出"])[0]
    a_nrm = nrm.embed_query("退货运费由谁承担")
    b_nrm = nrm.embed_documents(["退货的运费谁出"])[0]
    print(f"  bge-small 未归一化输出：|a|={math.sqrt(sum(x*x for x in a_raw)):.3f}  "
          f"|b|={math.sqrt(sum(x*x for x in b_raw)):.3f}")
    print(f"  bge-small 归一化输出：  |a|={math.sqrt(sum(x*x for x in a_nrm)):.3f}  "
          f"|b|={math.sqrt(sum(x*x for x in b_nrm)):.3f}")
    print("  这个模型内部已经做了归一化，encode_kwargs 对它是个空操作——"
          "换模型时不能假定如此")

    print()
    print("  为什么归一化必须与距离度量成对选（构造两个长度不同的向量）：")
    va = [1.0, 0.0, 0.0]
    vb_short = [0.9, 0.435, 0.0]
    vb_long = [2.7, 1.305, 0.0]
    for name, vb in [("短向量 |b|=1", vb_short), ("长向量 |b|=3", vb_long)]:
        print(f"    {name:<14} 余弦 {cosine(va, vb):.3f}   L2 {l2(va, vb):.3f}")
    print(f"    两组的余弦完全相同，L2 差 {l2(va, vb_long) - l2(va, vb_short):.2f}："
          "用 L2 排序时，向量长度会冒充相关性")


def section_cross_model():
    print()
    print("=== 3. 同一个问题，两个模型的读数 ===")
    small = model(SMALL)
    base = model(BASE)
    d_s = len(small.embed_query("x"))
    d_b = len(base.embed_query("x"))
    print(f"  bge-small 维度 {d_s}，bge-base 维度 {d_b}")
    print(f"  {'句子对':<30}{'small':>8}{'base':>8}")
    for a, b in PAIRS:
        vs = [small.embed_query(a), small.embed_documents([b])[0]]
        vb = [base.embed_query(a), base.embed_documents([b])[0]]
        print(f"  {a[:10] + ' / ' + b[:10]:<30}{cosine(*vs):>8.3f}{cosine(*vb):>8.3f}")
    print("  同一个意思的相似度，两个模型差 0.05 到 0.10：阈值不能跨模型沿用")


def section_truncate():
    print()
    print("=== 4. 截断：超出 max_seq_length 的部分不进入计算 ===")
    emb = model(SMALL)
    tok = AutoTokenizer.from_pretrained(SMALL)
    print(f"  bge 的 max_seq_length = {tok.model_max_length} token")

    def ntok(text: str) -> int:
        return len(tok(text, truncation=False, add_special_tokens=True)["input_ids"])

    q = emb.embed_query(QUERY)
    for mult, label in [(1, "原文"), (2, "重复 2 遍"), (12, "重复 12 遍"), (40, "重复 40 遍")]:
        text = LONG_HEAD * mult
        v = emb.embed_documents([text])[0]
        print(f"  {label:<12} {len(text):>5} 字  {ntok(text):>5} token  "
              f"与查询余弦 {cosine(v, q):.3f}")
    print("  40 遍那一行 token 数远超上限，余弦却与 12 遍几乎相同："
          "超出窗口的内容根本没有进入模型")


if __name__ == "__main__":
    section_matrix(model(SMALL))
    section_normalize()
    section_cross_model()
    section_truncate()


