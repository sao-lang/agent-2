"""四种切法与三种索引的取舍。

不联网、不用向量库。嵌入用字符 2-gram 向量代替（与第 14 章同一口径），
索引用暴力扫描 / 倒排 + 分桶 / 随机超平面树三种纯 Python 实现，
这样"召回率与耗时"的差别来自结构本身，而不是某次网络波动。
"""

from __future__ import annotations

import math
import random
import re
import time
from collections import Counter, defaultdict


# ---------------------------------------------------------------- 语料

DOC = """第 3 条 退货条件
质量问题退货，运费由商家承担，买家需在签收后 7 天内提交凭证。
第 4 条 非质量问题的退货
非质量问题退货，商品需保持未拆封，运费由买家承担，申请时限同样是 7 天。
第 5 条 生鲜类商品
生鲜类商品不支持无理由退货。若存在质量问题，请在签收后 24 小时内拍照并联系客服，
逾期不再受理。
第 6 条 发票
发票可在订单页申请，开票时限为下单后 30 天，超过时限不再补开。"""

QUESTIONS = {
    "生鲜能无理由退吗": "第5条生鲜类商品",
    "发票开票时限": "第6条发票",
    "非质量问题退货运费": "第4条非质量问题",
    "生鲜签收多久内要拍照": "第5条生鲜类商品",
}


# ---------------------------------------------------------------- 四种切法

def fixed_chunks(text: str, size: int = 40, overlap: int = 0) -> list[str]:
    """定长切：按字符数切，可选重叠。"""
    text = re.sub(r"\s+", "", text)
    step = size - overlap
    return [text[i:i + size] for i in range(0, len(text), step) if text[i:i + size]]


def heading_chunks(text: str) -> list[str]:
    """标题切：按"第 N 条"标题分段。"""
    parts = re.split(r"(?=第 \d+ 条)", text)
    return [re.sub(r"\s+", "", p) for p in parts if p.strip()]


def sentence_chunks(text: str, max_len: int = 60) -> list[str]:
    """语义切（近似）：按句号切，再把相邻短句并到 max_len 以内。"""
    sents = [s for s in re.split(r"(?<=。)", re.sub(r"\s+", "", text)) if s]
    out, buf = [], ""
    for s in sents:
        if len(buf) + len(s) <= max_len:
            buf += s
        else:
            if buf:
                out.append(buf)
            buf = s
    if buf:
        out.append(buf)
    return out


def parent_child(text: str, child_len: int = 24) -> list[tuple[str, str]]:
    """父子切：父块按标题，子块按定长。返回 (父块, 子块)。"""
    out = []
    for parent in heading_chunks(text):
        for i in range(0, len(parent), child_len):
            out.append((parent, parent[i:i + child_len]))
    return out


def question_chunks(text: str) -> list[str]:
    """问题式切：以每条政策为答案，反写一个能索引起它的问题，与原文一起存。"""
    heads = heading_chunks(text)
    prompts = {
        "第3条": "质量问题退货的运费谁承担，多久内要提交凭证",
        "第4条": "非质量问题退货有什么要求，运费谁出，时限多久",
        "第5条": "生鲜类商品能不能无理由退货，坏了多久内要拍照联系客服",
        "第6条": "发票怎么申请，开票时限是多少天",
    }
    out = []
    for h in heads:
        for key, q in prompts.items():
            if h.startswith(key):
                out.append(q)
                break
    return out


# ---------------------------------------------------------------- 向量与打分

def grams(text: str, n: int = 2) -> Counter:
    text = re.sub(r"\s+", "", text)
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))


def to_vec(c: Counter) -> dict[str, float]:
    norm = math.sqrt(sum(v * v for v in c.values())) or 1.0
    return {k: v / norm for k, v in c.items()}


def dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


# ---------------------------------------------------------------- 三种索引

class BruteIndex:
    """暴力：全部算一遍。"""
    name = "暴力"

    def __init__(self, vecs: list[dict[str, float]]):
        self.vecs = vecs

    def search(self, q: dict[str, float], k: int) -> list[int]:
        return sorted(range(len(self.vecs)), key=lambda i: -dot(q, self.vecs[i]))[:k]


class InvertedIndex:
    """倒排 + 分桶：只算共享至少一个 gram 的向量（IVF 的简化）。"""
    name = "倒排分桶"

    def __init__(self, vecs: list[dict[str, float]], top_grams: int = 200):
        counts: Counter = Counter()
        for v in vecs:
            counts.update(v.keys())
        keep = {g for g, _ in counts.most_common(top_grams)}
        self.buckets: dict[str, list[int]] = defaultdict(list)
        for i, v in enumerate(vecs):
            for g in v:
                if g in keep:
                    self.buckets[g].append(i)
        self.vecs = vecs

    def search(self, q: dict[str, float], k: int) -> list[int]:
        cand: set[int] = set()
        for g in q:
            cand.update(self.buckets.get(g, ()))
        if not cand:
            return BruteIndex(self.vecs).search(q, k)
        return sorted(cand, key=lambda i: -dot(q, self.vecs[i]))[:k]


class HyperplaneIndex:
    """随机超平面树：把空间切成叶，只在最近的几个叶里找（ANN 的简化）。"""
    name = "超平面树"

    def __init__(self, vecs: list[dict[str, float]], n_trees: int = 12, seed: int = 7):
        self.vecs = vecs
        self.dims = sorted({g for v in vecs for g in v})
        rnd = random.Random(seed)
        self.trees = []
        for _ in range(n_trees):
            planes = []
            for _ in range(4):                       # 每棵树 4 层，最多 16 个叶
                a = rnd.choice(self.dims)
                b = rnd.choice(self.dims)
                planes.append((a, b))
            leaves: dict[tuple[int, ...], list[int]] = defaultdict(list)
            for i, v in enumerate(vecs):
                leaves[self._key(v, planes)].append(i)
            self.trees.append((planes, leaves))

    @staticmethod
    def _key(v: dict[str, float], planes: list[tuple[str, str]]) -> tuple[int, ...]:
        return tuple(1 if v.get(a, 0.0) >= v.get(b, 0.0) else 0 for a, b in planes)

    def search(self, q: dict[str, float], k: int) -> list[int]:
        cand: set[int] = set()
        for planes, leaves in self.trees:
            cand.update(leaves.get(self._key(q, planes), []))
        if not cand:
            return BruteIndex(self.vecs).search(q, k)
        return sorted(cand, key=lambda i: -dot(q, self.vecs[i]))[:k]


# ---------------------------------------------------------------- 评测

def evaluate(chunks: list[str], index_cls, k: int = 1, repeat: int = 200,
             golden: dict[str, str] | None = None) -> dict:
    """golden: 问题 -> 期望文本标记。默认用 QUESTIONS；索引里没有原文时另有映射。"""
    golden = golden if golden is not None else QUESTIONS
    vecs = [to_vec(grams(c)) for c in chunks]
    index = index_cls(vecs)
    hit = 0
    for q, expect in golden.items():
        qv = to_vec(grams(q))
        ids = index.search(qv, k)
        if any(expect[:6] in chunks[i] for i in ids):
            hit += 1
    t0 = time.perf_counter()
    for _ in range(repeat):
        for q in golden:
            index.search(to_vec(grams(q)), k)
    ms = (time.perf_counter() - t0) * 1000 / (repeat * len(golden))
    return {"recall": hit / len(golden), "ms": ms, "n": len(chunks)}


def main() -> None:
    print("=== 1. 同一份文档，五种切法 ===")
    fixed = fixed_chunks(DOC, size=40)
    headed = heading_chunks(DOC)
    sent = sentence_chunks(DOC)
    pc = parent_child(DOC)
    qch = question_chunks(DOC)
    print(f"  定长(40)：{len(fixed)} 块  首块 {fixed[0][:24]!r}")
    print(f"  标题：    {len(headed)} 块  首块 {headed[0][:24]!r}")
    print(f"  句子：    {len(sent)} 块  首块 {sent[0][:24]!r}")
    print(f"  父子：    {len(pc)} 个子块（父块 {len({p for p, _ in pc})} 个）")
    print(f"  问题式：  {len(qch)} 块  首块 {qch[0]!r}")

    print()
    print("=== 2. 定长切把一条政策切断了 ===")
    for c in fixed_chunks(DOC, size=24):
        if "24" in c or "拍照" in c:
            print(f"  {c!r}")
    print("  <- 24 与拍照落在不同块里，问'多久内要拍照'时两块都只命中一半")

    print()
    print("=== 3. 切法决定召回上限（同一个索引，k=1）===")
    for label, cs, gold in [
        ("定长(40)", fixed, QUESTIONS),
        ("标题", headed, QUESTIONS),
        ("句子", sent, QUESTIONS),
        ("父子(子块)", [c for _, c in pc], QUESTIONS),
        # 问题式块的文字里没有原文，期望改用"块里提到的关键词"判定
        ("问题式", qch, {"生鲜能无理由退吗": "生鲜", "发票开票时限": "开票时限",
                          "非质量问题退货运费": "非质量问题", "生鲜签收多久内要拍照": "拍照"}),
    ]:
        r = evaluate(cs, BruteIndex, golden=gold)
        print(f"  {label:<10} 块数 {r['n']:>2}  召回 {r['recall']:.0%}")

    print()
    print("=== 4. 三种索引：召回与单次耗时（标题切，k=1）===")
    for idx in (BruteIndex, InvertedIndex, HyperplaneIndex):
        r = evaluate(headed, idx)
        print(f"  {idx.name:<6} 块数 {r['n']:>2}  召回 {r['recall']:.0%}  单次 {r['ms']:.3f} ms")

    print()
    print("=== 5. 块数放大到 200 之后：耗时分开，召回由切法决定 ===")
    # 每条政策复制 50 份，副本末尾加长度不同的标记，用来判断命中的是哪一份。
    # 标记本来就会把 50 份完全相同的块拆成不同向量——这是"几乎重复的块挤占预算"的样子。
    big = [f"{c}{'一' * j}" for j in range(50) for c in headed]
    gold_big = {q: "一" * 3 for q in QUESTIONS}
    for idx in (HyperplaneIndex, InvertedIndex, BruteIndex):
        ix = idx([to_vec(grams(c)) for c in big])
        got = []
        for q, mark in gold_big.items():
            ranked = ix.search(to_vec(grams(q)), len(big))
            target = next(n for n, i in enumerate(ranked) if big[i].endswith(mark))
            got.append(f"第 {target + 1} 位" + ("" if target < 2 else "（漏）"))
        t0 = time.perf_counter()
        for _ in range(20):
            for q in gold_big:
                ix.search(to_vec(grams(q)), 2)
        ms = (time.perf_counter() - t0) * 1000 / (20 * len(gold_big))
        print(f"  {idx.name:<6} 块数 {len(big):>3}  目标块排名 {got}  单次 {ms:.3f} ms")


if __name__ == "__main__":
    main()
