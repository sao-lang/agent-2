"""第 28 章示例：RAG 分层评测 + A/B 对比（检索部分不需要 API）。

运行：
    python code/ch41_eval/demo_rag_eval.py

它会做三件事：
  1. 只用 L1（检索层）评测两套配置，输出 A/B 对比表
  2. 展示"一次只改一个变量"的对比方式
  3. 列出失败样本（这才是最有用的部分）

加 --llm 参数会额外跑 L3 忠实度评测（需要 API key）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.rag_eval import EvalResult, Report, load_cases, retrieval_metrics  # noqa: E402
from common.retrieval import Index, hash_embed, split_fixed  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")
CASES = load_cases(ROOT / "evals" / "rag_cases.json")


def build_index(chunk_size: int, overlap: int) -> tuple[Index, dict[str, list[str]]]:
    idx = Index(embed=hash_embed)
    chunks = split_fixed(DOC, size=chunk_size, overlap=overlap)
    idx.add(chunks)
    return idx, {}


def gold_ids_for(case, idx: Index) -> list[str]:
    """把"答案锚点"映射到当前分块下的 chunk id。

    [!] 这里用的是**关键词匹配**来近似锚点，只为了能跑通定长切分的对比。
    第 28 章正文用的是真正的锚点（章节号 + meta），那样换分块策略也不会失效。
    """
    return [
        c.id for c in idx.chunks
        if all(k in c.text for k in case.must_contain)
    ]


def run_config(idx: Index, name: str) -> Report:
    results = []
    for case in CASES:
        if "对抗" in case.tags:
            continue  # 库外问题没有 gold，不参与 L1 评分
        retrieved = [(c.id, s) for c, s in idx.search(case.question, k=5)]
        retrieved_ids = [cid for cid, _ in retrieved]
        gold = gold_ids_for(case, idx)

        recall, mrr = retrieval_metrics(retrieved_ids, gold, ks=(1, 3, 5))
        top_texts = [next(c for c in idx.chunks if c.id == cid).text for cid in retrieved_ids[:3]]
        joined = " ".join(top_texts)
        contains = all(k in joined for k in case.must_contain) if case.must_contain else True

        results.append(
            EvalResult(
                case_id=case.id,
                question=case.question,
                answer="",  # L1 不生成答案
                contexts=top_texts,
                retrieved_ids=retrieved_ids,
                recall_at_k=recall,
                mrr=mrr,
                contains_required=contains,
            )
        )
    return Report(results)


def main() -> None:
    print(f"评测集：{len(CASES)} 条    语料：{len(DOC)} 字符\n")

    # ❗ 一次只改一个变量：这里只改 chunk size，overlap 保持一致
    configs = [(200, 40), (400, 40), (800, 40)]
    reports = {}
    for size, overlap in configs:
        idx, _ = build_index(size, overlap)
        reports[f"chunk={size}"] = run_config(idx, f"chunk={size}")

    # 对比表
    keys = ["recall@1", "recall@3", "recall@5", "mrr", "answer_contains_required"]
    print(f"{'配置':<12}" + "".join(f"{k:>24}" for k in keys))
    print("-" * (12 + 24 * len(keys)))
    for name, rep in reports.items():
        s = rep.summary()
        print(f"{name:<12}" + "".join(f"{s.get(k, 0):>24.3f}" for k in keys))

    # 基线 vs 最优
    baseline = reports["chunk=200"]
    best = max(reports.values(), key=lambda r: r.summary().get("mrr", 0))
    print("\n=== 基线 vs 最优（差值） ===")
    for k, (a, b, d) in baseline.diff(best).items():
        arrow = "^" if d > 0.005 else ("↓" if d < -0.005 else "=")
        print(f"  {k:<26}{a:>7.3f} → {b:>7.3f}   {arrow} {d:+.3f}")

    # 失败样本
    print("\n=== 失败样本（最优配置下仍答不全的） ===")
    fails = best.failures("contains_required")
    if not fails:
        print("  （无）")
    for r in fails:
        case = next(c for c in CASES if c.id == r.case_id)
        print(f"  [{r.case_id}] {r.question}")
        print(f"        需要包含：{case.must_contain}")
        print(f"        检索到：{r.retrieved_ids}")

    print("\n" + "=" * 74)
    print("这套评测方法的关键点")
    print("=" * 74)
    print("  1. gold_ids 用 **chunk id** 而不是文本 —— 分块策略变了，id 体系还稳定")
    print("  2. 一次只改一个变量 —— 这里只动 chunk size，overlap 固定")
    print("  3. 一定要看失败样本 —— 只报总分等于自己骗自己")
    print("  4. 指标要分层 —— recall 差还是生成差，决定了你要修哪一块")
    print("\n  [!] 这份语料只有 889 字，15 条样本，指标波动大。")
    print("     你需要在真实语料上标 50~100 条，才能得到可信的结论。")


if __name__ == "__main__":
    main()
