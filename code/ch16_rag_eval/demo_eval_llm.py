"""第 15 章示例 2：完整 RAG 流水线 + L3 忠实度评测（需要 API key）。

运行：
    python code/ch15_rag_eval/demo_eval_llm.py            # 全量
    python code/ch15_rag_eval/demo_eval_llm.py --limit 3  # 只跑 3 条（省钱）

它演示一个完整评测的四个环节：
  1. 检索 → 2. 生成（带引用） → 3. 规则校验（引用是否真实） → 4. Judge 打分（忠实度）

[!] 最后一定会让你做一件事：**校验 judge 自己靠不靠谱**。
   否则你所有"提升了 X%"的结论都建立在流沙上。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import Meter, get_settings, make_llm, usage_of  # noqa: E402
from common.rag_eval import (  # noqa: E402
    EvalResult,
    Report,
    check_citation,
    extract_citations,
    faithfulness_llm,
    load_cases,
    relevance_llm,
    retrieval_metrics,
)
from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

ANSWER_PROMPT = """你是售后客服助手。**只能**根据下面的材料回答，不能使用材料之外的知识。

要求：
1. 如果材料里没有答案，直接回答"资料中未提及"，不要猜
2. 每条结论后面用 [编号] 标注来源，例如 [c3]

材料：
{contexts}

问题：{question}"""


def build() -> Index:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=400))
    return idx


def gold_ids(case, idx: Index) -> list[str]:
    return [c.id for c in idx.chunks if any(k in c.text for k in case.must_contain)]


def main() -> None:
    s = get_settings()
    if s.api_key in ("missing", ""):
        print("[x] 需要 API key。请复制 .env-example 为 .env 并填入配置。")
        print("   如果只想看评测方法，请用：python code/ch15_rag_eval/demo_eval.py（离线，只跑 L1）")
        return

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    llm = make_llm()
    idx = build()
    cases = load_cases(ROOT / "evals" / "rag_cases.json")[:limit]

    meter = Meter()
    results: list[EvalResult] = []

    for case in cases:
        retrieved = idx.search(case.question, k=5)
        retrieved_ids = [c.id for c, _ in retrieved]
        contexts = [f"[{c.id}] {c.text}" for c, _ in retrieved]

        with meter.track(s.model, step="answer") as rec:
            msg = llm.invoke(ANSWER_PROMPT.format(contexts="\n\n".join(contexts), question=case.question))
            u = usage_of(msg)
            rec.input_tokens, rec.output_tokens = u["input_tokens"], u["output_tokens"]
        answer = str(msg.content)

        cites = extract_citations(answer)
        recall, mrr = retrieval_metrics(retrieved_ids, gold_ids(case, idx), ks=(1, 3, 5))
        faith = faithfulness_llm(llm, [c for c, _ in retrieved], answer)
        rel = relevance_llm(llm, case.question, answer)

        results.append(
            EvalResult(
                case_id=case.id,
                question=case.question,
                answer=answer,
                contexts=[c for c, _ in retrieved],
                retrieved_ids=retrieved_ids,
                recall_at_k=recall,
                mrr=mrr,
                contains_required=all(k in answer for k in case.must_contain),
                citation_ok=check_citation(answer, cites, set(retrieved_ids)),
                faithfulness=faith,
                relevance=rel,
            )
        )
        print(f"  [{case.id}] faith={faith:.2f} rel={rel:.2f} 引用={len(cites)} {cites}")

    report = Report(results)
    print("\n" + "=" * 74)
    print("完整报表")
    print("=" * 74)
    for k, v in report.summary().items():
        print(f"  {k:<26}{v:>8.3f}" if isinstance(v, float) else f"  {k:<26}{v}")

    cost = meter.summary()
    print(f"\n  成本：¥{cost['cost']:.4f}（{cost['calls']} 次调用）")
    print(f"  平均每题：¥{cost['cost'] / max(len(cases), 1):.5f}")

    print("\n" + "=" * 74)
    print("失败样本（这是最有价值的部分）")
    print("=" * 74)
    for metric, label in [("faithfulness", "忠实度<0.6（可能在编）"), ("relevance", "相关性<0.6（答偏了）")]:
        bad = report.failures(metric)
        if bad:
            print(f"\n  【{label}】")
            for r in bad[:3]:
                print(f"    [{r.case_id}] {r.question}")
                print(f"      答案：{r.answer[:80]}...")

    print("\n" + "=" * 74)
    print("[!] 最后一步：校验 judge 自己")
    print("=" * 74)
    print("  LLM-as-judge 也会错。你必须人工标 15~20 条，然后跑 validate_judge()。")
    print("  如果 agreement_rate < 0.8，你所有基于 judge 的结论都不可信。")
    print("\n  示例：")
    print("    from common.rag_eval import validate_judge")
    print("    samples = [(contexts, answer, human_score), ...]")
    print("    print(validate_judge(llm, samples))")


if __name__ == "__main__":
    main()
