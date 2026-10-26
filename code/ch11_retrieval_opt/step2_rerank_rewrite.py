"""第 11 章 step2：重排与查询改写——最后两个提升点（离线）。

运行：
    python code/ch10_retrieval_opt/step2_rerank_rewrite.py

上一级的痛点（step1）：混合检索把 Recall@3 从 70% 拉到 100%（加权后）。
                     但真实系统里 **Recall@3 ≠ 答案对** —— 因为 top-3 交给模型时，
                     模型可能只用了第 1 条。**排序质量**和**召回质量**是两件事。

这一级做什么：三个独立的提升手段，各自量化：
  ① **召回加宽 + 重排**：先取 top-20，再用更精确的打分挑 top-3
  ② **查询改写**：把口语改写成文档用语（这是最便宜的大杀器）
  ③ **对比三者叠加**，并给出成本/延迟

关键：**重排改善的是"排序"，查询改写改善的是"召回"。** 两者不能互相替代。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import BM25  # noqa: E402

DOCS = [
    ("d1", "退货政策：签收后七天内可申请无理由退货，商品需完好且不影响二次销售"),
    ("d2", "退货例外：定制商品、生鲜食品、已激活的数码产品不支持无理由退货"),
    ("d3", "换货流程：签收后十五天内出现质量问题可申请换新，需检测确认"),
    ("d4", "物流时效：江浙沪地区一到两天送达，其他地区三到五个工作日"),
    ("d5", "退款到账：审核通过后三到七个工作日原路退回，以发卡银行为准"),
    ("d6", "运费规则：质量问题由平台承担运费，非质量问题由买家承担"),
    ("d7", "优惠券规则：已使用的优惠券在退款时不返还，也不补发积分"),
    ("d8", "发票说明：退款后发票需一并退回，否则按税点扣除相应金额"),
    ("d9", "检测流程：商品寄回后五到七个工作日出具检测报告，遇节假日顺延"),
    ("d10", "会员权益：会员享受优先审核，退款时效缩短一个工作日"),
    ("d11", "售后入口：App 我的订单页面可发起售后申请，支持上传凭证"),
    ("d12", "客服时间：工作日九点到十八点可转人工，节假日仅有在线客服"),
    ("d13", "跨境订单：因涉及汇率与关税，退款周期可能延长至十五个工作日"),
    ("d14", "银行卡注销：退款将转为平台余额，可申请提现至本人实名账户"),
    ("d15", "复检申请：对检测结论有异议的，可在收到结论后七日内申请复检一次"),
]

# (口语查询, 改写后的查询, 正确答案 id)
CASES = [
    ("不想要了能退吗", "无理由退货 条件", "d1"),
    ("东西坏了怎么办", "质量问题 换新 检测", "d3"),
    ("钱啥时候到账", "退款到账 工作日", "d5"),
    ("运费谁掏", "退货运费 承担", "d6"),
    ("券还我么", "优惠券 退款 返还", "d7"),
    ("发票要不要寄回", "发票 退回 税点", "d8"),
    ("检测等几天", "检测报告 工作日", "d9"),
    ("会员快点吗", "会员 优先审核", "d10"),
    ("在哪申请", "售后入口 订单页面", "d11"),
    ("客服几点下班", "客服时间 十八点", "d12"),
    ("国外买的怎么退", "跨境订单 退款周期", "d13"),
    ("卡注销了", "银行卡注销 平台余额", "d14"),
    ("不认同检测结果", "复检申请 七日内", "d15"),
]


def tokens(text: str) -> set[str]:
    cn = re.findall(r"[\u4e00-\u9fff]{2}", text)
    return set(cn)


def embed(text: str, dim: int = 96) -> list[float]:
    import math

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


def main() -> None:
    ids = [i for i, _ in DOCS]
    texts = [t for _, t in DOCS]
    vecs = [embed(t) for t in texts]
    bm25 = BM25(texts)

    def stage1(q: str, k: int) -> list[int]:
        """粗排：向量 + BM25 加权 RRF。"""
        qv = embed(q)
        rv = sorted(range(len(texts)), key=lambda i: -cos(qv, vecs[i]))[:k]
        s = bm25.scores(q)
        rk = sorted(range(len(texts)), key=lambda i: -float(s[i]))[:k]
        score = [0.0] * len(texts)
        for rank, i in enumerate(rv):
            score[i] += 1.0 / (60 + rank + 1)
        for rank, i in enumerate(rk):
            score[i] += 3.0 / (60 + rank + 1)
        return sorted(range(len(texts)), key=lambda i: -score[i])[:k]

    def rerank(q: str, cand: list[int]) -> list[int]:
        """精排：用"查询词在**文档标题区**的覆盖度 + 同现强度"重新打分。

        真实系统这一步会用一个 cross-encoder 模型（query 和 doc 拼一起过一遍 transformer）。
        这里用可解释的代理指标，但有三个关键设计（缺一个就会变差）：

          ① **同时出现在文档前 12 字（通常是标题/主题词）权重更高**
             —— 文档的第一句往往就是它的主题
          ② **查查询里的实词**，过滤掉"了/吗/啥/么"这类无信息量的字
          ③ **用 bigram 而非单字**，避免"的"这种高频字带来噪音
        """
        STOP = {"了", "吗", "啥", "么", "的", "呢", "谁", "几", "点", "在", "有", "是", "要"}
        q_chars = [c for c in q if "\u4e00" <= c <= "\u9fff" and c not in STOP]
        q_bigrams = {q_chars[i] + q_chars[i + 1] for i in range(len(q_chars) - 1)} or set(q_chars)

        scored = []
        for i in cand:
            doc = texts[i]
            head = doc[:12]
            body = doc

            # ① 标题区命中（权重 3）
            head_hits = sum(1 for g in q_bigrams if g in head)
            # ② 全文命中（权重 1）
            body_hits = sum(1 for g in q_bigrams if g in body)
            # ③ 单字命中（权重 0.3，兜底）
            char_hits = sum(1 for c in q_chars if c in body) / max(1, len(q_chars))

            score = head_hits * 3.0 + body_hits * 1.0 + char_hits * 0.3
            scored.append((score, i))
        scored.sort(key=lambda x: -x[0])
        return [i for _, i in scored]

    REWRITE_MAP = {
        "不想要了": "无理由退货",
        "东西坏了": "质量问题",
        "钱啥时候到账": "退款到账",
        "运费谁掏": "退货运费",
        "券还我么": "优惠券 返还",
        "发票要不要寄回": "发票 退回",
        "检测等几天": "检测报告",
        "会员快点吗": "会员 优先审核",
        "在哪申请": "售后入口",
        "客服几点下班": "客服时间",
        "国外买的怎么退": "跨境订单 退款周期",
        "卡注销了": "银行卡注销",
        "不认同检测结果": "复检申请",
    }

    def rewrite(q: str) -> str:
        return REWRITE_MAP.get(q, q)

    def recall(fn, k: int = 3) -> float:
        hit = 0
        for q, _rw, gold in CASES:
            if ids.index(gold) in fn(q)[:k]:
                hit += 1
        return hit / len(CASES)

    # ---- 四种组合
    def base(q: str) -> list[int]:
        return stage1(q, 20)

    def reranked(q: str) -> list[int]:
        return rerank(q, stage1(q, 20))

    def rewritten(q: str) -> list[int]:
        return stage1(rewrite(q), 20)

    def both(q: str) -> list[int]:
        return rerank(rewrite(q), stage1(rewrite(q), 20))

    print("=" * 90)
    print(f"{len(CASES)} 条口语查询 × {len(DOCS)} 个文档")
    print("=" * 90)
    print(f"{'方案':<30}{'Recall@3':>10}{'Recall@1':>10}   代价")
    print("-" * 90)
    plans = [
        ("① 混合粗排（top-20→top-3）", base, "1 次向量 + 1 次 BM25"),
        ("② + 重排（top-20→精排→top-3）", reranked, "+ 20 次逐对打分"),
        ("③ + 查询改写（1 次 LLM 调用）", rewritten, "+ 1 次 LLM"),
        ("④ 重排 + 改写", both, "+ 1 次 LLM + 20 次打分"),
    ]
    res = {}
    for name, fn, cost in plans:
        r3 = recall(fn, 3)
        r1 = recall(fn, 1)
        res[name] = (r3, r1)
        print(f"{name:<30}{r3:>9.0%}{r1:>9.0%}   {cost}")
    print("-" * 90)

    print("\n" + "=" * 90)
    print("重排到底改变了什么：看一条真实的前后对比")
    print("=" * 90)
    q = "券还我么"
    cand = stage1(q, 20)
    before = cand[:3]
    after = rerank(q, cand)[:3]
    print(f"  查询：「{q}」（口语）  正确答案：d7")
    print()
    print("  重排前 top-3：")
    for i in before:
        mark = "★" if ids[i] == "d7" else " "
        print(f"    {mark} [{ids[i]}] {texts[i][:40]}")
    print()
    print("  重排后 top-3：")
    for i in after:
        mark = "★" if ids[i] == "d7" else " "
        print(f"    {mark} [{ids[i]}] {texts[i][:40]}")

    print("\n" + "=" * 90)
    print("查询改写为什么最划算")
    print("=" * 90)
    # 找一条"不改写时失败、改写后成功"的查询来演示
    demo = None
    for q, rw, gold in CASES:
        g = ids.index(gold)
        if g not in stage1(q, 20)[:3] and g in stage1(rw, 20)[:3]:
            demo = (q, rw, gold)
            break
    if demo is None:
        demo = CASES[0]
    q, rw, gold = demo
    print(f"  原始查询：{q!r}")
    print(f"    不改写 → {'✅' if ids.index(gold) in stage1(q, 20)[:3] else '❌'} top-3 命中 {gold}")
    print(f"  改写后：{rw!r}")
    print(f"    改写后 → {'✅' if ids.index(gold) in stage1(rw, 20)[:3] else '❌'} top-3 命中 {gold}")
    print()
    print("  为什么便宜：")
    print("    · 一次 LLM 调用（用最便宜的模型，100 token 内）")
    print("    · 改的是**问题**，不是索引 —— 索引不用重建")
    print("    · 可以缓存（同一句话只改一次）")
    print()
    print("  真实项目里的改写 prompt：")
    print("    '把用户的客服问题改写成检索用的关键词组，只输出关键词，'")
    print("    '用文档里的正式术语。例如：不想要了能退吗 → 无理由退货 条件'")

    print("\n" + "=" * 90)
    print("三者不能互相替代（这是本节最重要的一张表）")
    print("=" * 90)
    print(f"  {'手段':<16}{'改善什么':<22}{'对其他手段的影响'}")
    print("  " + "-" * 76)
    rows = [
        ("混合检索", "召回（找得到）", "重排的前置：候选里有正确答案才能排上来"),
        ("重排", "排序（排得前）", "召回没命中时，重排无能为力"),
        ("查询改写", "召回（找得到）", "对排序也有帮助（改写后词更匹配）"),
    ]
    for a, b, c in rows:
        print(f"  {a:<16}{b:<22}{c}")
    print("  " + "-" * 76)
    print()
    print("  判据：")
    print("    · Recall@20 高但 Recall@3 低 → **该重排**")
    print("    · Recall@20 本身就低 → **该查询改写**（或修分块，第 9 章）")
    print("    · 两者都低 → 先查分块，别急着上调优")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · **重排和查询改写解决不同问题**：前者改排序，后者改召回。")
    print("  · 先量 `Recall@20` 和 `Recall@3` 的差距：")
    print("      差距大 → 重排有效")
    print("      差距小但整体低 → 改写 / 分块")
    print("  · 重排的代价是「候选数 × 打分成本」——候选从 20 加到 100，成本涨 5 倍。")
    print("  · 查询改写要多一次 LLM 调用，但它改的是问题不是索引，**不用重建**。")
    print()
    print("  下一级（step3）：把这三件事串起来，用一张表决定「该不该上」。")

    assert res["④ 重排 + 改写"][0] >= res["① 混合粗排（top-20→top-3）"][0]


if __name__ == "__main__":
    main()
