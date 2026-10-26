"""第 29 章 step2：跑一次基线（离线，只算 L1 检索层，不花钱）。

运行：
    python code/ch41_eval/rag_step2_baseline.py

上一级的痛点：step1 只证明了"评测集没毛病"，但还不知道**系统现在多少分**。
这一级做什么：先跑一次什么都不改的基线，作为后面所有优化的对照物。

为什么要基线？
  没有基线的"优化"，你只能靠感觉说"好像变好了"。
  有了基线，你才能说"recall@5 从 0.90 到 1.00，涨了 0.10"。

基线用最朴素的配置：按标题切分 + 向量检索。
这是大多数人的第一版 RAG——也是本章要证明"不够用"的那一版。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.rag_eval import EvalCase, load_cases, retrieval_metrics  # noqa: E402
from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

BOUNDARY_TAGS = {"例外", "否定", "边界", "易错", "条件", "多要点", "多跳"}


def build_baseline() -> Index:
    """基线配置：按标题切分（上限 400 字）+ 向量检索。"""
    idx = Index(embed=hash_embed)
    texts = split_by_heading(DOC, max_chars=400)
    metas = []
    for t in texts:
        m = re.search(r"###\s*(\d+)\.(\d+)", t)
        metas.append({"sections": [f"{m.group(1)}.{m.group(2)}"] if m else []})
    idx.add(texts, metas)
    return idx


def gold_ids_for(case: EvalCase, idx: Index) -> list[str]:
    """把"答案锚点"映射成当前配置下的 chunk id。

    这是全章最重要的一个技术细节：
      · 用**文本**当 gold → 改一次分块就全对不上，评测集作废
      · 用 **chunk id** 当 gold → 分块换了 id 也换了，照样作废
      · 用**章节锚点**（1.1 / 2.3）当 gold → 分块怎么换都能重新映射，评测集永久可复用
    """
    if not case.anchor:
        return []  # 库外问题：本来就没有 gold
    return [c.id for c in idx.chunks if case.anchor in c.meta.get("sections", [])]


def avg(vals) -> float:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def main() -> None:
    idx = build_baseline()
    cases = load_cases(ROOT / "evals" / "rag_cases.json")

    rows = []
    for case in cases:
        retrieved = [c.id for c, _ in idx.search(case.question, k=5)]
        if not case.anchor:
            rows.append({"case": case, "retrieved": retrieved, "gold": [], "hit": None, "mrr": None, "kind": "对抗"})
            continue
        gold = gold_ids_for(case, idx)
        recall, mrr = retrieval_metrics(retrieved, gold, ks=(1, 3, 5))
        kind = "边界" if BOUNDARY_TAGS & set(case.tags) else "正例"
        rows.append({"case": case, "retrieved": retrieved, "gold": gold, "hit": recall, "mrr": mrr, "kind": kind})

    scored = [r for r in rows if r["hit"] is not None]

    print("=" * 74)
    print("基线：按标题切分（上限 400 字）+ 向量检索 top-5")
    print("=" * 74)
    print(f"语料：{len(DOC)} 字符 → {len(idx.chunks)} 个 chunk")
    print(f"评测集：{len(rows)} 条（有 gold 的 {len(scored)} 条，库外问题 {len(rows) - len(scored)} 条）\n")

    print(f"{'指标':<26}{'基线':>8}")
    print("-" * 36)
    for k in (1, 3, 5):
        print(f"{f'recall@{k}':<26}{avg([r['hit'].get(k) for r in scored]):>8.3f}")
    print(f"{'mrr':<26}{avg([r['mrr'] for r in scored]):>8.3f}")

    print("\n" + "=" * 74)
    print("切片：按难度拆开看（这一步比总分重要得多）")
    print("=" * 74)
    print(f"{'类别':<8}{'条数':>6}{'recall@1':>12}{'recall@5':>12}{'mrr':>10}")
    print("-" * 48)
    for kind in ("正例", "边界"):
        rs = [r for r in scored if r["kind"] == kind]
        print(
            f"{kind:<8}{len(rs):>6}"
            f"{avg([r['hit'].get(1) for r in rs]):>12.3f}"
            f"{avg([r['hit'].get(5) for r in rs]):>12.3f}"
            f"{avg([r['mrr'] for r in rs]):>10.3f}"
        )

    print("\n" + "=" * 74)
    print("逐条明细（[x] = 答案所在的小节没进 top-5）")
    print("=" * 74)
    for r in rows:
        c = r["case"]
        if r["hit"] is None:
            print(f"  -   [{c.id}] {c.question}  → 库外问题，L1 不评分")
        elif r["hit"].get(5):
            print(f"  [v]   [{c.id}] {c.question}")
        else:
            print(f"  [x]   [{c.id}] {c.question}")
            print(f"        gold={r['gold']}  retrieved={r['retrieved']}")

    _conclude(scored)


def _conclude(scored) -> None:
    print("\n" + "=" * 74)
    print("基线结论")
    print("=" * 74)
    r1 = avg([r["hit"].get(1) for r in scored])
    r5 = avg([r["hit"].get(5) for r in scored])
    print(f"  recall@1 = {r1:.2f}    recall@5 = {r5:.2f}")
    print("  recall@1 和 recall@5 差得越多，说明「找得到但排不准」——这是**排序**问题；")
    print("  两个都低，说明「压根没找到」——这是**分块 / 召回**问题。")
    print("\n  下一级先解决「排不准」：只加一个概念——把两路召回的结果合并。")


if __name__ == "__main__":
    main()
