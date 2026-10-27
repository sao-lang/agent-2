"""混合检索、RRF 融合、重排与查询改写。

不联网。三套"检索器"都是纯 Python：
- 向量：字符 2-gram 余弦（与前面几章同一口径）
- BM25：字级倒排 + 标准 BM25 打分
- 重排：交叉打分（把查询与块拼在一起算词项重合，模拟 cross-encoder）

语料是故意布成"两路各错一批"的：验证类问题向量答得出、关键词问题 BM25 稳，
而"月卡退款"这类措辞与文档不一致的问题两路都排不进前几名，留着重排来救。
"""

from __future__ import annotations

import math
import re
from collections import Counter


CHUNKS = [
    "第3条 质量问题退货，运费由商家承担，买家需在签收后7天内提交凭证。",           # C0
    "第4条 非质量问题退货，商品需保持未拆封，运费由买家承担。",                     # C1
    "第5条 生鲜类商品不支持无理由退货。若存在质量问题，请在签收后24小时内拍照并联系客服。",  # C2
    "第6条 发票可在订单页申请，开票时限为下单后30天。",                             # C3
    "第7条 退款审核通过后，原路退回，到账时间以银行为准。",                         # C4
    "第8条 会员积分可在订单完成后24小时内到账，退款时积分同步扣回。",               # C5
    "第9条 商品出库前可取消订单，款项3个工作日内退回。",                            # C6
    "第10条 会员月卡按自然月计费，退款时按未使用天数折算，已使用部分不予退还。",     # C7
    "第11条 换货可在签收后15天内申请，更换商品不收取运费。",                        # C8
]

# 查询 -> (正确块下标, 这条查询想验证什么)
CASES = [
    ("会员积分多久到账", 5, "关键词高度重合"),
    ("月卡没用完能退吗", 7, "退款/退 两种措辞"),
    ("优惠券退款后还能用吗", 5, "8 个块里没有一条讲优惠券，知识库缺这一条"),
    ("生鲜商品七天无理由退货吗", 2, "文档里有原话"),
    ("发票怎么开", 3, "短查询"),
]


def grams(text: str, n: int = 2) -> Counter:
    text = re.sub(r"\s+", "", text)
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))


def cosine(a: Counter, b: Counter) -> float:
    num = sum(a[k] * b[k] for k in set(a) & set(b))
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


# ---------------------------------------------------------------- 向量检索

def vector_rank(query: str, chunks: list[str]) -> list[int]:
    q = grams(query)
    return sorted(range(len(chunks)), key=lambda i: -cosine(q, grams(chunks[i])))


# ---------------------------------------------------------------- BM25

def char_terms(text: str) -> list[str]:
    """字级切分：中文不用空格，按单字切，BM25 仍然成立。"""
    return [c for c in re.sub(r"\s+", "", text)]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [char_terms(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(len(d) for d in self.docs) / len(self.docs)
        self.df: Counter = Counter()
        for d in self.docs:
            self.df.update(set(d))
        self.n = len(self.docs)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: str, i: int) -> float:
        doc = self.docs[i]
        tf = Counter(doc)
        total = 0.0
        for term in set(char_terms(query)):
            if term not in tf:
                continue
            f = tf[term]
            total += self.idf(term) * f * (self.k1 + 1) / (
                f + self.k1 * (1 - self.b + self.b * len(doc) / self.avg))
        return total


def bm25_rank(query: str, chunks: list[str]) -> list[int]:
    bm = BM25(chunks)
    return sorted(range(len(chunks)), key=lambda i: -bm.score(query, i))


# ---------------------------------------------------------------- 融合

def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：只看得票名次，不看分数。"""
    score: dict[int, float] = {}
    for ranking in rankings:
        for pos, doc in enumerate(ranking, start=1):
            score[doc] = score.get(doc, 0.0) + 1 / (k + pos)
    return sorted(score.items(), key=lambda x: -x[1])


# ---------------------------------------------------------------- 重排

def rerank_score(query: str, chunk: str) -> float:
    """交叉打分：查询二元组在块里的命中率 + 靠前二元组的加权命中（模拟 cross-encoder）。"""
    q_bi = list(grams(query))
    ds = set(grams(chunk))
    cover = sum(1 for t in q_bi if t in ds) / len(q_bi)
    pos_bonus = sum(1 / (i + 1) for i, t in enumerate(q_bi) if t in ds)
    return cover + 0.05 * pos_bonus


def rerank(query: str, chunks: list[str], cand: list[int], top: int = 3) -> list[int]:
    return sorted(cand, key=lambda i: -rerank_score(query, chunks[i]))[:top]


# ---------------------------------------------------------------- 查询改写

SYNONYMS = {"退": "退款", "买": "下单", "坏了": "质量问题"}

def synonym_rewrite(query: str) -> str:
    """查询规划式的改写：口语词换成文档里的规范词。"""
    out = query
    for a, b in SYNONYMS.items():
        out = out.replace(a, b)
    return out


SYNONYMS = {"换个货": "换货", "退": "退款", "买了": "下单"}

MULTI = {
    "月卡没用完能退吗": ["会员月卡退款按未使用天数折算", "月卡已使用部分不予退还"],
    "想换个货怎么弄": ["换货在签收后15天内申请", "换货要收运费吗"],
}

HYDE = {
    "月卡没用完能退吗": "会员月卡退款按未使用天数折算，已使用部分不予退还。",
    "想换个货怎么弄": "换货可在签收后15天内申请，更换商品不收取运费。",
    # 故意写坏的假设文档：语义上对，但全用了检索版里没有的词，用来看误伤
    "换货多长时间有效": "置换办理的有效期与收费说明。",
}

# 一条措辞与文档不一致、改写能救回来的查询
REWRITE_QUERY = "想换个货怎么弄"
REWRITE_GOLD = 8
# 一条改写会误伤的查询：答案在 C8，坏 HyDE 会把它挤下去
BAD_REWRITE_QUERY = "换货多长时间有效"
BAD_REWRITE_GOLD = 8


def multi_query(query: str) -> list[str]:
    """多查询扩展：原查询 + 同义词替换后的查询 + 事先写好的规范化说法。"""
    expanded = query
    for a, b in SYNONYMS.items():
        expanded = expanded.replace(a, b)
    return [query, expanded, *MULTI.get(query, [])]


def rewritten_rank(query: str, chunks: list[str], strategy: str) -> list[int]:
    if strategy == "raw":
        return vector_rank(query, chunks)
    if strategy == "syn":
        return vector_rank(synonym_rewrite(query), chunks)
    if strategy == "multi":
        return [d for d, _ in rrf([vector_rank(q, chunks) for q in multi_query(query)])]
    if strategy == "hyde":
        return [d for d, _ in rrf([vector_rank(HYDE.get(query, query), chunks),
                                   vector_rank(query, chunks)])]
    raise ValueError(strategy)


def top3(ranking: list[int]) -> str:
    return " > ".join(f"C{i}" for i in ranking[:3])


def main() -> None:
    print("=== 1. 五条查询，两路检索各自的排名 ===")
    for q, gold, note in CASES:
        v, b = vector_rank(q, CHUNKS), bm25_rank(q, CHUNKS)
        f = [d for d, _ in rrf([v, b])]
        print(f"\n  {q}   正确=C{gold}（{note}）")
        print(f"    向量 {top3(v)}{'  ✓' if v[0] == gold else ''}")
        print(f"    BM25 {top3(b)}{'  ✓' if b[0] == gold else ''}")
        print(f"    RRF  {top3(f)}{'  ✓' if f[0] == gold else ''}")

    print()
    print("=== 2. Top1 命中数 ===")
    counts: Counter = Counter()
    for q, gold, _ in CASES:
        f = [d for d, _ in rrf([vector_rank(q, CHUNKS), bm25_rank(q, CHUNKS)])]
        counts["向量"] += vector_rank(q, CHUNKS)[0] == gold
        counts["BM25"] += bm25_rank(q, CHUNKS)[0] == gold
        counts["RRF"] += f[0] == gold
    for k, v in counts.items():
        print(f"  {k:<5} {v}/{len(CASES)}")

    print()
    print("=== 3. 重排：只重排已召回的前 5 ===")
    for q, gold, _ in CASES:
        cand = [d for d, _ in rrf([vector_rank(q, CHUNKS), bm25_rank(q, CHUNKS)])][:5]
        after = rerank(q, CHUNKS, cand, top=3)
        print(f"  {q}")
        print(f"    融合后 {top3(cand)}   重排后 {top3(after)}{'  ✓' if after[0] == gold else ''}")

    print()
    print("=== 4. 查询改写的四种做法（向量检索）===")
    for q in (REWRITE_QUERY, BAD_REWRITE_QUERY):
        gold = REWRITE_GOLD if q == REWRITE_QUERY else BAD_REWRITE_GOLD
        print(f"  {q}   正确=C{gold}")
        for s in ("raw", "syn", "multi", "hyde"):
            r = rewritten_rank(q, CHUNKS, s)
            print(f"    {s:<6} {top3(r)}{'  ✓' if r[0] == gold else ''}")


if __name__ == "__main__":
    main()
