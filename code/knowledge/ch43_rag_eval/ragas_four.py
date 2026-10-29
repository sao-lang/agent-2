"""四个指标怎么算出来的：一个样本，逐项展开。

不联网。四个指标（faithfulness / answer relevancy / context precision / context recall）
都用字面重合做代理，把每一步的中间量打出来 —— 目的是看清"这个数是怎么来的"，
不是复现 RAGAS 的实现（它用嵌入与 LLM）。

代理指标只能用于版本间比较：绝对值没有意义，方向有意义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

QUESTION = "退款多久到账？"
# 顺序很重要：第 1 条不相关，第 2 条才是答案所在
CONTEXTS = [
    ("faq#6", "节假日顺延。", 0),
    ("faq#5", "退款一般在 3 个工作日内到账。", 1),
]
ANSWER = "退款会在 3 个工作日内到账，且需要支付 5% 手续费。"
TRUTH = ["退款 3 个工作日内到账", "退款原路返回"]


@dataclass
class Calc:
    name: str
    value: float
    detail: list[str]


def bigrams(text: str) -> set[str]:
    t = re.sub(r"[^\u4e00-\u9fff]", "", text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def overlap(a: str, b: str) -> float:
    """字面重合度：交集 / 较短一方。"""
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / min(len(ba), len(bb))


def split_claims(answer: str) -> list[str]:
    return [c.strip() for c in re.split(r"[。，,；]", answer) if c.strip()]


def faithfulness() -> Calc:
    claims = split_claims(ANSWER)
    detail = []
    ok = 0
    for c in claims:
        best = max(((overlap(c, t), cid) for cid, t, rel in CONTEXTS if rel == 1),
                   default=(0.0, "-"))
        hit = best[0] >= 0.5
        ok += 1 if hit else 0
        detail.append(f"    {c!r:<30} 最高重合 {best[0]:.2f}（{best[1]}） -> "
                      f"{'有依据' if hit else '无依据'}")
    detail.append(f"    有依据 {ok} / {len(claims)} = {ok / len(claims):.3f}")
    return Calc("faithfulness", ok / len(claims), detail)


def answer_relevancy() -> Calc:
    q, a = bigrams(QUESTION), bigrams(ANSWER)
    inter = len(q & a)
    p = inter / len(a) if a else 0.0
    r = inter / len(q) if q else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    detail = [
        f"    问题二元组 {len(q)} 个，答案二元组 {len(a)} 个，交集 {inter} 个",
        f"    精确率 {inter}/{len(a)} = {p:.3f}，召回率 {inter}/{len(q)} = {r:.3f}",
        f"    F1 = {f1:.3f}（代理指标，绝对值不可解释，只看版本间方向）",
    ]
    return Calc("answer_relevancy", f1, detail)


def context_precision() -> Calc:
    """RAGAS 口径：sum_k(precision@k × rel_k) / 相关的条数。"""
    relevant_total = sum(rel for _, _, rel in CONTEXTS)
    detail = []
    total = 0.0
    for k, (cid, _, rel) in enumerate(CONTEXTS, start=1):
        pk = sum(r for _, _, r in CONTEXTS[:k]) / k
        total += pk * rel
        detail.append(f"    k={k} {cid} rel={rel}  precision@{k}={pk:.2f}  "
                      f"贡献 {pk * rel:.2f}")
    value = total / relevant_total if relevant_total else 0.0
    detail.append(f"    加权和 {total:.2f} / 相关条数 {relevant_total} = {value:.3f}")
    return Calc("context_precision", value, detail)


def context_recall() -> Calc:
    detail = []
    covered = 0
    for t in TRUTH:
        best = max(((overlap(t, ctx), cid) for cid, ctx, rel in CONTEXTS if rel == 1),
                   default=(0.0, "-"))
        hit = best[0] >= 0.5
        covered += 1 if hit else 0
        detail.append(f"    标准答案句 {t!r:<22} 最高重合 {best[0]:.2f} -> "
                      f"{'覆盖' if hit else '未覆盖'}")
    detail.append(f"    覆盖 {covered} / {len(TRUTH)} = {covered / len(TRUTH):.3f}")
    return Calc("context_recall", covered / len(TRUTH), detail)


def main() -> None:
    print("=== 0. 一个样本 ===")
    print(f"  问题：{QUESTION}")
    print(f"  回答：{ANSWER}")
    print("  检索到的块（按顺序）：")
    for cid, text, rel in CONTEXTS:
        print(f"    {cid}  rel={rel}  {text}")

    print()
    print("=== 1. 四个指标的逐项计算 ===")
    for calc in (faithfulness(), answer_relevancy(), context_precision(), context_recall()):
        print(f"  {calc.name} = {calc.value:.3f}")
        for line in calc.detail:
            print(line)
        print()

    print("=== 2. 一个样本的结论 ===")
    print("  faithfulness 低：回答里有上下文不支持的断言（5% 手续费）")
    print("  context_precision 0.5：第 1 条不相关块排在前面")
    print("  context_recall 0.5：标准答案的两句只覆盖了一句")
    print("  answer_relevancy 只说明'答的和问的相关'，不看对错")


if __name__ == "__main__":
    main()
