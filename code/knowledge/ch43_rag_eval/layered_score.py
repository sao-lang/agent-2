"""分层打分：检索层与生成层分开评，失败才能归因。

不联网。三个样本，每个都带：问题、检索到的块（含相关性标注）、回答、标准答案。
先算检索层（召回、命中位置、上下文精度），再算生成层（忠实度、覆盖率），
最后把失败归到某一层——这是 RAG 评测唯一有诊断价值的输出。

相关性标注由人给（rel=1 表示这块能支撑正确答案）。示例把它们直接写在数据里。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STOP = set("的了吗呢吧是就都而及与或用有在对于把被让给那这")


@dataclass
class Chunk:
    cid: str
    text: str
    rel: int = 0                 # 1 = 能支撑标准答案


@dataclass
class Sample:
    name: str
    question: str
    chunks: list[Chunk] = field(default_factory=list)
    answer: str = ""
    truth: list[str] = field(default_factory=list)


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\u4e00-\u9fff]{2,}", text)} - STOP


def overlap(a: str, b: str) -> float:
    """两个短句的字面重合度：交集 / 较短一方。"""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


SAMPLES = [
    Sample(
        "A 检索漏召回",
        "生鲜订单可以无理由退货吗？",
        chunks=[
            Chunk("policy#1", "签收后 7 天内可无理由退货。", rel=0),
            Chunk("policy#2", "非质量问题退货运费由买家承担。", rel=0),
        ],
        answer="可以，签收后 7 天内都能无理由退货。",
        truth=["生鲜商品不支持无理由退货", "质量问题才可以申请退货"],
    ),
    Sample(
        "B 排序把答案压到第 4",
        "定制商品能退吗？",
        chunks=[
            Chunk("faq#1", "退货需要保持商品完好。", rel=0),
            Chunk("faq#2", "运费规则见下。", rel=0),
            Chunk("faq#3", "会员退货有专属通道。", rel=0),
            Chunk("policy#9", "定制商品不支持无理由退货。", rel=1),
        ],
        answer="定制品类没有明确说明，按通用规则应当可以退。",
        truth=["定制商品不支持无理由退货"],
    ),
    Sample(
        "C 生成加了一条",
        "退款多久到账？",
        chunks=[
            Chunk("faq#5", "退款一般在 3 个工作日内到账。", rel=1),
            Chunk("faq#6", "节假日顺延。", rel=0),
        ],
        answer="3 个工作日内到账，且需要支付 5% 手续费。",
        truth=["退款 3 个工作日内到账"],
    ),
]


def retrieval_metrics(s: Sample, top_k: int = 3) -> dict:
    top = s.chunks[:top_k]
    relevant = [c for c in s.chunks if c.rel == 1]
    hit = [c.cid for c in top if c.rel == 1]
    rank = next((i + 1 for i, c in enumerate(top) if c.rel == 1), None)
    rank_all = next((i + 1 for i, c in enumerate(s.chunks) if c.rel == 1), None)
    return {
        "relevant_total": len(relevant),
        "hit_in_topk": len(hit),
        "recall": len(hit) / len(relevant) if relevant else 0.0,
        "first_hit_rank": rank,
        "rank_all": rank_all,
        "precision": len(hit) / len(top) if top else 0.0,
    }


def generation_metrics(s: Sample) -> dict:
    claims = [c for c in re.split(r"[。，；]", s.answer) if c.strip()]
    supported = 0
    for c in claims:
        if any(overlap(c, ch.text) >= 0.5 for ch in s.chunks if ch.rel == 1):
            supported += 1
    covered = sum(1 for t in s.truth
                  if any(overlap(t, ch.text) >= 0.4 for ch in s.chunks if ch.rel == 1))
    return {
        "claims": len(claims),
        "supported": supported,
        "faithfulness": supported / len(claims) if claims else 0.0,
        "truth_covered": covered,
        "truth_total": len(s.truth),
        "coverage": covered / len(s.truth) if s.truth else 0.0,
    }


def attribute(s: Sample, r: dict, g: dict) -> str:
    """按两个层的指标给出归因。"""
    if r["rank_all"] is None:
        return "检索层：知识库里没有能支撑正确答案的块"
    if r["recall"] == 0 and r["rank_all"] > 3:
        return f"检索层：答案排在第 {r['rank_all']} 位，被 top-3 截断"
    if g["coverage"] < 1.0:
        return "生成层：答案漏了标准答案里的要点"
    if g["faithfulness"] < 1.0:
        return "生成层：答案里有上下文不支持的断言"
    return "两层都通过"


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 三个样本的分层打分 ===")
    for s in SAMPLES:
        r = retrieval_metrics(s)
        g = generation_metrics(s)
        print(f"  [{s.name}] {s.question}")
        print(f"    检索层：召回 {r['recall']:.0%}（{r['hit_in_topk']}/{r['relevant_total']}）"
              f"  首命中位置 {r['first_hit_rank']}  精度 {r['precision']:.0%}")
        print(f"    生成层：忠实度 {g['faithfulness']:.0%}（{g['supported']}/{g['claims']} 条断言有依据）"
              f"  要点覆盖 {g['coverage']:.0%}（{g['truth_covered']}/{g['truth_total']}）")
        print(f"    归因：{attribute(s, r, g)}")
        print()

    print("=== 2. 总分分不出修法 ===")
    for s in SAMPLES:
        r = retrieval_metrics(s)
        g = generation_metrics(s)
        total = (r["recall"] + g["faithfulness"] + g["coverage"]) / 3
        print(f"  {pad(s.name, 22)}总分 {total:.2f}")
    print("  <- A 与 B 都是低分，但一个要补知识库、一个要调 top-k：")
    print("     总分相同的样本，修法可能完全不同")

    print()
    print("=== 3. 锚点映射：每条断言能指回哪一块 ===")
    s = SAMPLES[2]
    claims = [c for c in re.split(r"[。，；]", s.answer) if c.strip()]
    for c in claims:
        hit = [ch.cid for ch in s.chunks if overlap(c, ch.text) >= 0.5]
        print(f"  {c!r:<28} -> {hit or '无锚点（幻觉）'}")


if __name__ == "__main__":
    main()
