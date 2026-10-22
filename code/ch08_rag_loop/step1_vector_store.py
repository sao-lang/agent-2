"""第 8 章 step1：向量库到底做了什么——手写一个，才敢用现成的（离线）。

运行：
    python code/ch08_rag_loop/step1_vector_store.py

上一级的痛点（第 7 章）：你会算余弦相似度了。但真实项目有 10 万篇文档：
                     每次查询都算 10 万次余弦？太慢。

这一级做什么：手写一个最小向量库，然后**用数字看清三件事**：
  ① 暴力检索为什么慢（O(N)）
  ② 索引（IVF/HNSW）用"少算一点"换速度，代价是**召回率不是 100%**
  ③ "元数据过滤"为什么必须在检索之前做，而不是之后

这不是为了让你造轮子——是为了让你用 Qdrant/Milvus 时知道
**哪些参数在影响什么，以及为什么召回率不是 100%。**
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field


# ============================================================ 基础
def embed(text: str, dim: int = 64) -> list[float]:
    """字符 2-gram 哈希嵌入（同第 7 章，简化版）。"""
    v = [0.0] * dim
    t = text.replace(" ", "")
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


@dataclass
class Doc:
    id: str
    text: str
    meta: dict
    vec: list[float] = field(default_factory=list)


# ============================================================ 语料（10 个语义主题）
TOPICS = [
    "退货政策：签收后七天内可申请无理由退货，商品需完好",
    "退货例外：定制商品、生鲜、已激活数码产品不支持无理由退货",
    "换货流程：质量问题可在十五天内申请换新，需检测确认",
    "物流时效：江浙沪一到两天，其他地区三到五个工作日",
    "退款到账：审核通过后三到七个工作日原路退回",
    "运费规则：质量问题由平台承担，非质量问题由买家承担",
    "优惠券规则：已使用的优惠券退款时不返还",
    "发票说明：退款后发票需一并退回，否则扣除税点",
    "检测流程：寄回后五到七个工作日出具检测报告",
    "会员权益：会员享受优先审核，退款时效缩短一天",
]

CATEGORIES = ["政策", "FAQ", "操作指引"]

# 每个主题一个"聚类中心" —— 等价于"k-means 已经训练好了"
CENTERS = [embed(t) for t in TOPICS]


def _match(meta: dict, where: dict | None) -> bool:
    if not where:
        return True
    return all(meta.get(k) == v for k, v in where.items())


# ============================================================ 暴力检索
class FlatStore:
    """FLAT / 暴力检索：每次都和所有向量比一次。

    **这是召回率 100% 的基准** —— 任何近似索引都要和它对比。
    """

    def __init__(self) -> None:
        self.docs: list[Doc] = []

    def add(self, docs: list[Doc]) -> None:
        for d in docs:
            if not d.vec:
                d.vec = embed(d.text)
            self.docs.append(d)

    def search(self, q: str, k: int = 5, where: dict | None = None) -> list[tuple[Doc, float]]:
        qv = embed(q)
        # 元数据过滤在**检索之前**做：先缩小候选集，再算相似度
        cands = [d for d in self.docs if _match(d.meta, where)]
        scored = [(d, cos(qv, d.vec)) for d in cands]
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


# ============================================================ 近似检索（IVF）
class IVFStore:
    """IVF（倒排文件索引）的教学实现：先分配到最近的簇，查询时只搜最近的 nprobe 个簇。

    真实 IVF 用 k-means 训练聚类中心；这里用**手工主题中心**
    （等价于"聚类已经训练好了"），但**取舍完全一样**：
    少搜几个簇 = 快，但可能漏掉正确答案。
    """

    def __init__(self) -> None:
        self.lists: list[list[Doc]] = [[] for _ in CENTERS]

    def add(self, docs: list[Doc]) -> None:
        for d in docs:
            if not d.vec:
                d.vec = embed(d.text)
            self.lists[self._nearest(d.vec)].append(d)

    @staticmethod
    def _nearest(vec: list[float]) -> int:
        return max(range(len(CENTERS)), key=lambda i: cos(vec, CENTERS[i]))

    def _probe_order(self, qv: list[float]) -> list[int]:
        return sorted(range(len(CENTERS)), key=lambda i: -cos(qv, CENTERS[i]))

    def search(self, q: str, k: int = 5, nprobe: int = 1, where: dict | None = None) -> list[tuple[Doc, float]]:
        qv = embed(q)
        cands: list[Doc] = []
        for i in self._probe_order(qv)[:nprobe]:
            cands += self.lists[i]
        cands = [d for d in cands if _match(d.meta, where)]
        scored = [(d, cos(qv, d.vec)) for d in cands]
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def probe_candidates(self, q: str, nprobe: int) -> int:
        return sum(len(self.lists[i]) for i in self._probe_order(embed(q))[:nprobe])

    def bucket_sizes(self) -> list[int]:
        return [len(b) for b in self.lists]


# ============================================================ 造数据
def make_docs(n: int, seed: int = 0) -> list[Doc]:
    rng = random.Random(seed)
    docs = []
    for i in range(n):
        base = TOPICS[i % len(TOPICS)]
        noise = "".join(
            rng.choice("的一是在不了有和人这中大为上个国我以要他") for _ in range(rng.randint(0, 20))
        )
        docs.append(
            Doc(id=f"d{i:05d}", text=base + noise, meta={"category": CATEGORIES[i % 3], "lang": "zh"})
        )
    return docs


# ============================================================ 主流程
def main() -> None:
    print("=" * 84)
    print("① 暴力检索 vs 近似检索：速度和召回率的取舍")
    print("=" * 84)

    q = "退款多久到账"
    for n in (200, 2_000, 10_000):
        docs = make_docs(n)
        flat = FlatStore()
        flat.add(docs)
        ivf = IVFStore()
        ivf.add(docs)

        t0 = time.perf_counter()
        truth = flat.search(q, k=5)
        t_flat = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        approx = ivf.search(q, k=5, nprobe=1)
        t_ivf = (time.perf_counter() - t0) * 1000

        truth_ids = {d.id for d, _ in truth}
        approx_ids = {d.id for d, _ in approx}
        recall = len(truth_ids & approx_ids) / len(truth_ids) if truth_ids else 0

        print(f"\n  N = {n:>6,}")
        print(f"    FLAT   耗时 {t_flat:>7.2f}ms   命中 {len(truth)} 条")
        print(f"    IVF(1) 耗时 {t_ivf:>7.2f}ms   命中 {len(approx)} 条   召回率 {recall:.0%}")
        if n == 10_000:
            print(f"    → 加速 {t_flat / max(t_ivf, 0.001):.1f}x，但漏了 {len(truth_ids - approx_ids)} 条")

    print("\n" + "=" * 84)
    print("② 为什么召回率不是 100%：正确答案常常「跨主题」")
    print("=" * 84)
    docs = make_docs(2_000)
    ivf = IVFStore()
    ivf.add(docs)
    sizes = ivf.bucket_sizes()
    print(f"  10 个簇的大小：min={min(sizes)} max={max(sizes)} 平均={sum(sizes) / len(sizes):.0f}")
    print("  → 每个簇对应一个语义主题（真实 IVF 用 k-means 自动学出来）")
    print()
    flat = FlatStore()
    flat.add(docs)

    # 故意用"跨主题"的查询：正确答案分布在多个簇里
    cross = "退货 退款 时效 发票"
    truth_ids = {d.id for d, _ in flat.search(cross, k=5)}
    print("  它的正确答案会散落在『退款到账』『退货政策』『发票说明』『物流时效』等多个簇里。")
    print()
    print(f"  {'nprobe':>7}{'候选数':>8}{'耗时(ms)':>10}{'召回率':>9}")
    print("  " + "-" * 40)
    for np_ in (1, 2, 3, 5, 8, 10):
        t0 = time.perf_counter()
        got = ivf.search(cross, k=5, nprobe=np_)
        dt = (time.perf_counter() - t0) * 1000
        r = len(truth_ids & {d.id for d, _ in got}) / len(truth_ids) if truth_ids else 0
        print(f"  {np_:>7}{ivf.probe_candidates(cross, np_):>8}{dt:>10.2f}{r:>9.0%}")
    print("  " + "-" * 40)
    print("  **nprobe 是「召回率 vs 延迟」的旋钮。** 真实系统默认 1–10，")
    print("  高召回场景（法务、医疗）要调到 32+ 甚至直接用 FLAT。")
    print()
    print("  → 单主题查询（如「退款多久到账」）nprobe=1 就够，召回率 100%")
    print("  → 跨主题查询 nprobe=1 会漏，必须加大")
    print("  **这就是为什么「我的检索怎么老是漏一条」——查询本身跨主题。**")

    print("\n" + "=" * 84)
    print("③ 元数据过滤：为什么必须在检索之前")
    print("=" * 84)
    flat = FlatStore()
    flat.add(make_docs(2_000))
    print(f"  查询：「{q}」  过滤条件：category == 'FAQ'")
    print()
    before = flat.search(q, k=5)
    after = flat.search(q, k=5, where={"category": "FAQ"})
    print("  先检索再过滤（top-5 里再筛）：")
    kept = [d for d, _ in before if d.meta["category"] == "FAQ"]
    print(f"     拿到 5 条，过滤后只剩 {len(kept)} 条 → **结果不够 k 条**")
    for d, s in before:
        mark = "✓" if d.meta["category"] == "FAQ" else "✗"
        print(f"     {mark} {s:.3f} [{d.meta['category']}] {d.text[:22]}")
    print()
    print("  先过滤再检索（在候选集里筛）：")
    print(f"     拿到 {len(after)} 条，全部符合条件")
    for d, s in after[:3]:
        print(f"     ✓ {s:.3f} [{d.meta['category']}] {d.text[:22]}")
    print("     …")
    print()
    print("  **这是真实项目里最常见的 bug 之一。**")
    print("  先检索后过滤会让'过滤后结果不足 k 条'，甚至一条都没有——")
    print("  而你会以为'没有相关内容'，其实是**过滤把正确答案筛掉了**。")

    print("\n" + "=" * 84)
    print("结论：向量库替你做的四件事")
    print("=" * 84)
    print("  ① 存向量并持久化（重启不丢）")
    print("  ② 快速找最近邻（索引：FLAT / HNSW / IVF）")
    print("  ③ **元数据过滤**（必须在检索前，否则结果不足）")
    print("  ④ 增删改（重新嵌入、删除旧版本）")
    print()
    print("  两个该记住的数字：")
    print("    · 暴力检索 O(N)：1 万条约几十 ms，10 万条就上百 ms")
    print("    · 近似检索用 nprobe/ef 换速度：召回率 90–99%，**不是 100%**")
    print()
    print("  下一级（step2）：把'检索 → 拼 prompt → 生成'接成 RAG 最小闭环。")

    assert len(make_docs(50)) == 50
    assert sum(ivf.bucket_sizes()) == 2_000


if __name__ == "__main__":
    main()
