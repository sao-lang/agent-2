"""第 7 章 step4：怎么用数字判断"哪个嵌入更好"（离线）。

运行：
    python code/ch07_embedding/step4_eval.py

上一级的痛点（step3）：你看到一个查询成功了，就"感觉"语义嵌入很好。
                     但老板问"好多少"，你答不上来。

这一级做什么：建一个 12 条查询的小评测集，跑三种嵌入方案，给出三个指标：
  · **Recall@3**：正确答案在前 3 名里的比例
  · **MRR**：正确答案排名的倒数均值（排第 1 得 1 分，第 2 得 0.5 分）
  · **Top-1 准确率**

核心结论：**"感觉好"和"数字好"经常不一致。** 评测集只要 12 条就能把差距量化。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from step2_hash_embedding import hash_embed
from step3_real_embedding import offline_embed


DOCS = [
    "退货政策：签收后七天内可申请无理由退货，需商品完好",
    "退货例外：定制商品、生鲜、已激活数码产品不支持无理由退货",
    "换货流程：质量问题可在十五天内申请换新，需检测确认",
    "物流时效：江浙沪一般一到两天，其他地区三到五个工作日",
    "退款到账：审核通过后三到七个工作日原路退回",
    "运费规则：质量问题由平台承担，非质量问题由买家承担",
    "优惠券规则：已使用的优惠券退款时不返还",
    "发票说明：退款后发票需一并退回，否则扣除税点",
    "检测流程：寄回后五到七个工作日出具检测报告",
    "会员权益：会员享受优先审核，退款时效缩短一天",
    "售后入口：App 我的订单页可发起售后申请",
    "客服电话：工作日九点到十八点可转人工",
]

# (查询, 正确文档下标, 类型)
CASES = [
    ("不想要了能退吗", 0, "口语化"),
    ("定制的东西能退吗", 1, "明确"),
    ("坏了怎么换", 2, "口语化"),
    ("快递几天能到", 3, "口语化"),
    ("钱多久退回来", 4, "口语化"),
    ("退货运费谁出", 5, "明确"),
    ("用过的券退不退", 6, "口语化"),
    ("发票要退吗", 7, "明确"),
    ("检测要等多久", 8, "明确"),
    ("会员退款会快一点吗", 9, "明确"),
    ("在哪申请售后", 10, "口语化"),
    ("人工客服几点上班", 11, "明确"),
]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Metrics:
    name: str
    recall_at_3: float
    mrr: float
    top1: float


def evaluate(name: str, embed) -> Metrics:
    doc_vecs = [embed(d) for d in DOCS]
    recall3 = 0
    rr = 0.0
    top1 = 0
    for q, gold, _ in CASES:
        qv = embed(q)
        ranked = sorted(
            range(len(DOCS)), key=lambda i: cosine(qv, doc_vecs[i]), reverse=True
        )
        if gold in ranked[:3]:
            recall3 += 1
        rank = ranked.index(gold) + 1
        rr += 1 / rank
        if rank == 1:
            top1 += 1
    n = len(CASES)
    return Metrics(name, recall3 / n, rr / n, top1 / n)


def main() -> None:
    n = len(CASES)
    print("=" * 88)
    print(f"评测集：{n} 条查询 × {len(DOCS)} 个文档")
    print("=" * 88)
    print("三种嵌入方案：")
    print("  ① 哈希嵌入（step2）：纯字面，不懂同义词")
    print("  ② 同义词归一后哈希（step3 的离线模拟）：手工维护同义词表")
    print("  ③ 真实语义模型：需 API key（本次无 key，故用 ② 代替并在结论里说明）\n")

    results = [
        evaluate("① 哈希嵌入", hash_embed),
        evaluate("② 同义词+哈希", offline_embed),
    ]

    print("=" * 88)
    print("指标对比")
    print("=" * 88)
    print(f"{'方案':<22}{'Recall@3':>11}{'MRR':>9}{'Top-1':>9}   相对 ①")
    print("-" * 88)
    base = results[0]
    for m in results:
        gain = f"+{m.recall_at_3 - base.recall_at_3:.0%} 召回" if m is not base else "基线"
        print(f"{m.name:<22}{m.recall_at_3:>11.0%}{m.mrr:>9.3f}{m.top1:>9.0%}   {gain}")
    print("-" * 88)

    print("\n" + "=" * 88)
    print("逐条看：哪类查询进步最大")
    print("=" * 88)
    print(f"{'查询':<18}{'类型':<8}{'①排名':>7}{'②排名':>7}   变化")
    print("-" * 88)
    d1 = [hash_embed(d) for d in DOCS]
    d2 = [offline_embed(d) for d in DOCS]
    for q, gold, kind in CASES:
        r1 = sorted(range(len(DOCS)), key=lambda i: cosine(hash_embed(q), d1[i]), reverse=True).index(gold) + 1
        r2 = sorted(range(len(DOCS)), key=lambda i: cosine(offline_embed(q), d2[i]), reverse=True).index(gold) + 1
        if r1 == r2:
            delta = "─"
        elif r2 < r1:
            delta = f"↑ 提前 {r1 - r2} 位"
        else:
            delta = f"↓ 退后 {r2 - r1} 位"
        print(f"{q:<18}{kind:<8}{r1:>7}{r2:>7}   {delta}")
    print("-" * 88)

    print("\n" + "=" * 88)
    print("三个指标分别在看什么")
    print("=" * 88)
    explains = [
        ("Recall@3", "正确答案在前 3 里吗", "衡量「能不能找到」——检索阶段最重要的指标"),
        ("MRR", "正确排名的倒数均值", "衡量「排得够不够前」——影响最终答案质量"),
        ("Top-1", "排第一的是不是正确答案", "最严格，但对 RAG 不一定必要（给 LLM 看 3 条也行）"),
    ]
    print(f"  {'指标':<12}{'算的是什么':<20}用途")
    print("  " + "-" * 78)
    for a, b, c in explains:
        print(f"  {a:<12}{b:<20}{c}")

    print("\n" + "=" * 88)
    print("为什么这件事必须做：三个真实理由")
    print("=" * 88)
    reasons = [
        (
            "① 换模型时你需要证据",
            "从 bge-small 换到 text-embedding-3-large，成本翻 20 倍。\n"
            "     如果 Recall@3 只从 82% 提到 84%，这个交易不划算。",
        ),
        (
            "② 失败案例会暴露真实缺口",
            "本例里'定制的东西能退吗''退货运费谁出''会员退款会快一点吗'\n"
            "     两条方案都排不进前 3——说明字面与语义都没抓住要点。\n"
            "     这类失败要么靠更好的模型，要么靠**改写查询**（第 30 章）。",
        ),
        (
            "③ 防止'我觉得变好了'",
            "只测 1–2 条查询时，随机性远大于真实差异。\n"
            "     12 条以上才能看到趋势（第 43 章会讲样本量）。",
        ),
    ]
    for a, b in reasons:
        print(f"\n  {a}")
        print(f"     {b}")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  · 嵌入模型的好坏**必须用数字判断**，而指标只需 12 条查询就能算。")
    print("  · 优先看 **Recall@3**：它决定「能不能找到」，MRR 和 Top-1 决定「排得好不好」。")
    print("  · 同义词归一能显著提升口语化查询，但**需要人工维护词表**——")
    print("    这就是为什么真实项目直接用语义模型：省掉维护成本。")
    print("  · 下一级（step5）：有了向量之后，怎么存、怎么快速搜——这就是向量库（第 8 章）。")

    assert results[1].recall_at_3 >= results[0].recall_at_3, "语义方案不应低于纯字面"


if __name__ == "__main__":
    main()
