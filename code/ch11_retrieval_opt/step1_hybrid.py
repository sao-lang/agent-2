"""第 11 章 step1：混合检索——向量 + 关键词，各自救对方一次（离线）。

运行：
    python code/ch10_retrieval_opt/step1_hybrid.py

上一级的痛点（第 9 章）：你把分块调好了，Recall@3 到了 89%。
                     但剩下 11% 怎么都上不去——因为它们需要**两种不同的检索能力**。

这一级做什么：跑 20 条查询，让两种检索各自暴露短板，然后融合：
  · **向量检索**强于"换说法"（语义），弱于"精确词"（订单号、型号、条款号）
  · **BM25 关键词**强于"精确词"，弱于"换说法"
  · **混合（RRF 融合）**两边都拿分

关键：融合方式用 **RRF（Reciprocal Rank Fusion）**，
     因为它不需要把两种分数"归一化"——那个归一化是很多人踩的坑。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import BM25  # noqa: E402

DOCS = [
    ("d1", "退货政策：签收后七天内可申请无理由退货，商品需完好"),
    ("d2", "退货例外：定制商品、生鲜食品、已激活的数码产品不支持无理由退货"),
    ("d3", "换货流程：签收后十五天内出现质量问题可申请换新"),
    ("d4", "物流时效：江浙沪一到两天，其他地区三到五个工作日"),
    ("d5", "退款到账：审核通过后三到七个工作日原路退回"),
    ("d6", "运费规则：质量问题由平台承担，非质量问题由买家承担"),
    ("d7", "优惠券规则：已使用的优惠券退款时不返还"),
    ("d8", "发票说明：退款后发票需一并退回，否则扣除税点"),
    ("d9", "订单 A12345 特殊处理：该订单为团购订单，退款需整单处理"),
    ("d10", "订单 B98765 特殊处理：该订单使用企业账户，需财务审核"),
    ("d11", "型号 XR-2000 的耳机支持主动降噪，保修期两年"),
    ("d12", "型号 XR-3000 的耳机为旗舰款，保修期三年"),
    ("d13", "会员权益：会员享受优先审核，退款时效缩短一天"),
    ("d14", "售后入口：App 我的订单页面可发起售后申请"),
    ("d15", "检测流程：商品寄回后五到七个工作日出具检测报告"),
]

# (查询, 正确答案 id, 需要什么能力)
CASES = [
    ("退款多久到账？", "d5", "语义"),
    ("钱什么时候退回来", "d5", "语义（换说法）"),
    ("不想要了能退吗", "d1", "语义（换说法）"),
    ("东西坏了怎么换", "d3", "语义（换说法）"),
    ("快递几天能到", "d4", "语义（换说法）"),
    ("用过的券退不退", "d7", "语义（换说法）"),
    ("A12345", "d9", "**精确（订单号）**"),
    ("B98765", "d10", "**精确（订单号）**"),
    ("XR-2000", "d11", "**精确（型号）**"),
    ("XR-3000", "d12", "**精确（型号）**"),
    ("XR-3000 保修几年", "d12", "精确+语义"),
    ("A12345 能退吗", "d9", "精确+语义"),
    ("运费谁出", "d6", "语义"),
    ("发票要退吗", "d8", "语义"),
    ("会员有啥好处", "d13", "语义（换说法）"),
    ("在哪申请售后", "d14", "语义（换说法）"),
    ("检测要等多久", "d15", "语义"),
    ("XR-2000 降噪", "d11", "精确+语义"),
    ("企业账户退款", "d10", "语义"),
    ("团购订单退款", "d9", "语义"),
]


def embed(text: str, dim: int = 96) -> list[float]:
    v = [0.0] * dim
    t = text.replace(" ", "").replace("\n", "")
    for i in range(max(1, len(t) - 1)):
        g = t[i : i + 2]
        h = 0
        for ch in g:
            h = (h * 131 + ord(ch)) % 1_000_003
        v[h % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def main() -> None:
    ids = [i for i, _ in DOCS]
    texts = [t for _, t in DOCS]
    vecs = [embed(t) for t in texts]
    bm25 = BM25(texts)

    def vec_rank(q: str) -> list[int]:
        qv = embed(q)
        return sorted(range(len(texts)), key=lambda i: -cos(qv, vecs[i]))

    def kw_rank(q: str) -> list[int]:
        s = bm25.scores(q)
        return sorted(range(len(texts)), key=lambda i: -float(s[i]))

    def rrf(q: str, k: int = 60) -> list[int]:
        """Reciprocal Rank Fusion：只用排名，不用原始分数。

        关键：`k` 越大，排名差异被压得越平（越"民主"）；k 越小越偏向头部。
        k=60 是业界常用默认值。
        """
        rv, rk = vec_rank(q), kw_rank(q)
        score = [0.0] * len(texts)
        for rank, i in enumerate(rv):
            score[i] += 1.0 / (k + rank + 1)
        for rank, i in enumerate(rk):
            score[i] += 1.0 / (k + rank + 1)
        return sorted(range(len(texts)), key=lambda i: -score[i])

    def rrf_weighted(q: str, w_vec: float, w_kw: float, k: int = 60) -> list[int]:
        """加权 RRF：当一路明显更强时可以给更高权重（但要靠数据定，不能拍脑袋）。"""
        rv, rk = vec_rank(q), kw_rank(q)
        score = [0.0] * len(texts)
        for rank, i in enumerate(rv):
            score[i] += w_vec / (k + rank + 1)
        for rank, i in enumerate(rk):
            score[i] += w_kw / (k + rank + 1)
        return sorted(range(len(texts)), key=lambda i: -score[i])

    def evaluate(fn, k: int = 3) -> tuple[float, dict[str, int]]:
        hit = 0
        by_kind: dict[str, list[int]] = {}
        for q, gold, kind in CASES:
            ranked = fn(q)[:k]
            ok = ids.index(gold) in ranked
            hit += ok
            bucket = "精确" if "精确" in kind else "语义"
            by_kind.setdefault(bucket, [0, 0])
            by_kind[bucket][0] += ok
            by_kind[bucket][1] += 1
        return hit / len(CASES), {k2: v[0] / v[1] for k2, v in by_kind.items()}

    print("=" * 92)
    print(f"{len(CASES)} 条查询 × {len(DOCS)} 个文档，Recall@3 对比")
    print("=" * 92)
    print(f"{'方法':<22}{'总 Recall@3':>13}{'精确类':>9}{'语义类':>9}   说明")
    print("-" * 92)
    rows = [
        ("① 纯向量", vec_rank, "擅长换说法，但本例用哈希嵌入，很弱"),
        ("② 纯 BM25", kw_rank, "本例中反而最强（中文 bigram 很有效）"),
        ("③ 混合（1:1 RRF）", rrf, "两个弱项互相拖累 → 低于纯 BM25"),
        ("④ 混合（加权 1:3）", lambda q: rrf_weighted(q, 1.0, 3.0), "按实测给 BM25 更高权重"),
    ]
    results = {}
    for name, fn, note in rows:
        overall, by = evaluate(fn)
        results[name] = (overall, by)
        print(f"{name:<22}{overall:>12.0%}{by.get('精确', 0):>9.0%}{by.get('语义', 0):>9.0%}   {note}")
    print("-" * 92)

    print("\n" + "=" * 92)
    print("⚠️ 一个反直觉的结果：1:1 混合反而不如纯 BM25")
    print("=" * 92)
    print("  纯 BM25 95%，1:1 混合只有 80% —— **混合不是无脑更好**。")
    print()
    print("  原因：本例的向量检索用的是**哈希嵌入**（字面级），它本身就弱：")
    print("    · 它把「不想要了能退吗」检索失败")
    print("    · 在 RRF 里它给错文档加了一份分数，把 BM25 排对的挤掉了")
    print()
    print("  **这就是为什么必须先量出每一路单独的水平。** 具体做法：")
    print("    ① 先测纯向量、纯 BM25 各自的 Recall")
    print("    ② 如果一路明显更强，混合时给它更高权重（加权 RRF）")
    print("    ③ 如果一路几乎没用（比如对比 1:1 和纯强的那路），**就别混**")
    print()
    print("  表里第 ④ 行（加权 1:3）就是把 BM25 的权重提上来后的效果。")
    print()
    print("  > 真实项目里，如果你用的是**真正的语义嵌入模型**（不是哈希），")
    print("  > 纯向量的语义类 Recall 会远高于本例，那时 1:1 混合通常才是最优。")
    print("  > **本例故意用弱嵌入，就是为了让你看到「混合不是免费午餐」这件事。**")

    print("\n" + "=" * 92)
    print("逐条看：各自在哪里翻车")
    print("=" * 92)
    print(f"{'查询':<22}{'类型':<14}{'向量':>6}{'BM25':>7}{'混合':>7}")
    print("-" * 92)
    for q, gold, kind in CASES:
        g = ids.index(gold)
        v = "✅" if g in vec_rank(q)[:3] else "❌"
        b = "✅" if g in kw_rank(q)[:3] else "❌"
        h = "✅" if g in rrf(q)[:3] else "❌"
        print(f"{q:<22}{kind:<14}{v:>6}{b:>7}{h:>7}")
    print("-" * 92)

    print("\n" + "=" * 92)
    print("为什么纯向量在'订单号/型号'上必输")
    print("=" * 92)
    q = "A12345"
    qv = embed(q)
    print(f"  查询：「{q}」")
    print("  纯向量排名前 3：")
    for i in vec_rank(q)[:3]:
        print(f"    {cos(qv, vecs[i]):.3f} [{ids[i]}] {texts[i][:38]}")
    print("  BM25 排名前 3：")
    s = bm25.scores(q)
    for i in kw_rank(q)[:3]:
        print(f"    {float(s[i]):.3f} [{ids[i]}] {texts[i][:38]}")
    print()
    print("  → 向量检索把「A12345」和别的订单号看成「差不多的短字符串」（字符高度重叠）")
    print("  → BM25 命中精确 token，直接把 d9 排第一")
    print()
    print("  **结论：任何「精确标识符」（订单号、型号、条款号、人名、SKU）都必须有关键词检索。**")

    print("\n" + "=" * 92)
    print("为什么纯 BM25 在'换说法'上必输")
    print("=" * 92)
    q = "不想要了能退吗"
    s = bm25.scores(q)
    print(f"  查询：「{q}」")
    print("  BM25 排名前 3：")
    for i in kw_rank(q)[:3]:
        print(f"    {float(s[i]):.3f} [{ids[i]}] {texts[i][:38]}")
    print()
    print("  → 文档里写的是「无理由退货」，没有任何词和「不想要了」重叠")
    print("  → BM25 全靠 bigram（'不要'、'想要'）碰运气")
    print("  → 向量检索能靠语义找到 d1（第 7 章已证明）")
    print()
    print("  **结论：面向 C 端的自然语言查询，必须有向量检索。**")

    print("\n" + "=" * 92)
    print("融合方式对比：为什么用 RRF 而不是加权求和")
    print("=" * 92)
    q = "A12345"
    qv = embed(q)
    vs = [cos(qv, vecs[i]) for i in range(len(texts))]
    ks = [float(x) for x in bm25.scores(q)]
    print(f"  查询「{q}」的两种原始分数：")
    print(f"    向量分数范围：{min(vs):.3f} ~ {max(vs):.3f}")
    print(f"    BM25 分数范围：{min(ks):.3f} ~ {max(ks):.3f}")
    print()
    print("  如果直接 `0.5 * 向量 + 0.5 * BM25`：")
    print(f"    BM25 的最大值是向量最大值的 {max(ks) / max(vs):.1f} 倍")
    print("    → 权重名义上 50:50，实际 BM25 单方面主导")
    print()
    print("  如果做 min-max 归一化再加权：")
    print("    → 归一化依赖当次候选集，候选集一变结果就变，**不可复现**")
    print()
    print("  RRF 的做法：**只看名次**")
    print("    score(d) = Σ 1/(k + rank_d)，k 通常取 60")
    print("    → 免疫量纲差异，也不需要归一化，且对异常分数不敏感")

    print("\n" + "=" * 92)
    print("结论")
    print("=" * 92)
    print("  · **两种检索不是竞争关系，是互补关系。** 各自救对方一次。")
    print("  · 有精确标识符（订单号/型号/条款号）→ 必须有 BM25")
    print("  · 有自然语言查询（口语/换说法）→ 必须有向量")
    print("  · 融合用 RRF：只看排名，不碰原始分数，免疫量纲问题")
    print()
    print("  下一级（step2）：混合之后还是有排错的——加一层**重排（rerank）**。")

    assert results["④ 混合（加权 1:3）"][0] >= results["② 纯 BM25"][0] - 0.001
    pass


if __name__ == "__main__":
    main()
