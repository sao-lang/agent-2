"""第 28 章 step5：一次只改一个变量，跑四轮优化，其中两轮**没变好**。

运行：
    python code/ch14_rag_eval/step5_optimize.py

上一级的痛点：知道了"要分层评测"，但还不知道**怎么证明某次改动真的有用**。
这一级做什么：把四轮改动放进同一张表，每轮只动一个变量，并给出方向判断。

四轮改动：
  0. 基线        按标题切分 + 向量检索
  1. 换召回      向量 + BM25 + RRF          （对应第 30 章）→ 有效
  2. 换切分      父子分块（小块检索）         （对应第 29 章）→ 持平
  3. 加重排      对候选做一次逐词重排        （对应第 30 章）→ 有效
  4. 叠改写      多查询 + 融合 + 重排        （可能是**无效优化**）

为什么必须保留"没变好"的那一轮？
  因为真实世界里大部分改动**都无效**。只会报好消息的评测表，
  迟早会让你在汇报时翻车。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.hybrid_search import RetrievalPipeline  # noqa: E402
from common.rag_eval import EvalCase, load_cases, retrieval_metrics  # noqa: E402
from common.retrieval import Index, hash_embed, split_by_heading, split_parent_child  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")
CASES = load_cases(ROOT / "evals" / "rag_cases.json")


def section_of(text: str) -> list[str]:
    m = re.search(r"###\s*(\d+)\.(\d+)", text)
    return [f"{m.group(1)}.{m.group(2)}"] if m else []


def build_heading() -> Index:
    """基线：按标题切分，一个 chunk 就是一个小节。"""
    idx = Index(embed=hash_embed)
    texts = split_by_heading(DOC, max_chars=400)
    idx.add(texts, [{"sections": section_of(t)} for t in texts])
    return idx


def build_parent_child() -> Index:
    """父子分块：用小块检索，命中后再把整节交给模型读。

    它解决的是"一句话被切断"：搜的是短块，读的是完整小节。
    检索单元的 meta 里记着它属于哪个小节，所以 gold 仍然能映射。
    """
    idx = Index(embed=hash_embed)
    texts: list[str] = []
    metas: list[dict] = []
    for section_text in split_by_heading(DOC, max_chars=1200):
        secs = section_of(section_text)
        if not secs:
            texts.append(section_text)
            metas.append({"sections": []})
            continue
        for child, _parent in split_parent_child(section_text, parent_size=1200, child_size=180):
            texts.append(child)
            metas.append({"sections": secs})
    idx.add(texts, metas)
    return idx


def gold_ids_for(case: EvalCase, idx: Index) -> list[str]:
    return [c.id for c in idx.chunks if case.anchor and case.anchor in c.meta.get("sections", [])]


def evaluate(idx: Index, mode: str) -> dict[str, float]:
    pipe = RetrievalPipeline(index=idx, mode=mode)
    rs = []
    for case in CASES:
        if not case.anchor:
            continue
        got = [cid for cid, _ in pipe.search(case.question, k=5)]
        recall, mrr = retrieval_metrics(got, gold_ids_for(case, idx), ks=(1, 3, 5))
        rs.append((recall, mrr))
    n = len(rs)
    return {
        "recall@1": sum(1 for r, _ in rs if r[1]) / n,
        "recall@5": sum(1 for r, _ in rs if r[5]) / n,
        "mrr": sum(m for _, m in rs) / n,
    }


def main() -> None:
    rows: list[tuple[str, dict[str, float], str]] = []

    idx_a = build_heading()
    rows.append(("0 基线", evaluate(idx_a, "dense"), "按标题切 + 纯向量"))
    rows.append(("1 换召回", evaluate(idx_a, "hybrid"), "加 BM25 + RRF"))

    idx_b = build_parent_child()
    rows.append(("2 换切分", evaluate(idx_b, "hybrid"), "父子分块（小块检索）"))
    rows.append(("3 加重排", evaluate(idx_b, "rerank"), "对候选做逐词重排"))
    rows.append(("4 叠改写", evaluate(idx_b, "full"), "多查询 + 融合 + 重排"))

    keys = ["recall@1", "recall@5", "mrr"]
    print("=" * 80)
    print("四轮优化（每轮只改一个变量）")
    print("=" * 80)
    print(f"{'轮次':<10}{'改动':<26}" + "".join(f"{k:>12}" for k in keys))
    print("-" * 80)
    prev = rows[0][1]
    for name, m, what in rows:
        cells = []
        for k in keys:
            d = m[k] - prev[k]
            arrow = "^" if d > 0.004 else ("↓" if d < -0.004 else "=")
            cells.append(f"{m[k]:.3f}{arrow}")
        print(f"{name:<10}{what:<26}" + "".join(f"{c:>12}" for c in cells))
        prev = m

    print("\n" + "=" * 80)
    print("逐轮判断（方向 + 解释）")
    print("=" * 80)
    for i in range(1, len(rows)):
        name, m, what = rows[i]
        base = rows[i - 1][1]
        d5 = m["recall@5"] - base["recall@5"]
        d1 = m["recall@1"] - base["recall@1"]
        if d5 > 0.004:
            verdict = f"有效：recall@5 {d5:+.3f}"
        elif d1 > 0.004:
            verdict = f"部分有效：recall@5 持平，但 recall@1 {d1:+.3f}（答案排得更前了）"
        elif d5 < -0.004:
            verdict = f"有害：recall@5 {d5:+.3f}，应该回滚"
        else:
            verdict = "持平：指标没动"
        print(f"  {name}（{what}）→ {verdict}")

    print("\n" + "=" * 80)
    print("★ 两轮「没变好」，原因完全不同")
    print("=" * 80)
    print("  第 2 轮 换切分 —— 持平，但**不是因为它错**：")
    print("    这份语料只有 889 字，按标题切出来的块本来就不长，")
    print("    父子分块没有用武之地。语料变成 10 万字以后，它会明显起作用。")
    print("    → 教训：**无效 ≠ 错误**。要看它想解决的那个问题在不在你的场景里。")
    print()
    print("  第 4 轮 叠改写 —— 持平，这次是**真的白改**：")
    print("    查询改写解决的是「用户用词和文档用词不同」。")
    print("    但本轮的失败样本已经被第 3 轮的重排吃掉了，改写没有新的失败样本可救。")
    print("    → 教训：**优化要对着失败样本做**，不对着「听起来更高级」做。")

    print("\n" + "=" * 80)
    print("最终结论")
    print("=" * 80)
    best = max(rows, key=lambda r: (r[1]["recall@5"], r[1]["mrr"]))
    base = rows[0][1]
    print(f"  基线        recall@5={base['recall@5']:.3f}  mrr={base['mrr']:.3f}")
    print(f"  最优({best[0]})  recall@5={best[1]['recall@5']:.3f}  mrr={best[1]['mrr']:.3f}")
    print(f"  提升        recall@5 {best[1]['recall@5'] - base['recall@5']:+.3f}"
          f"  mrr {best[1]['mrr'] - base['mrr']:+.3f}")
    print("\n  [!] 有 gold 的样本只有 20 条，±0.05 以内的差异可能只是噪音。")
    print("     要下结论，至少要有 100 条以上样本（见本章 N.7 练习 1）。")


if __name__ == "__main__":
    main()
