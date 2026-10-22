"""第 28 章产出：RAG 检索质量的回归门禁（离线，无 API，秒级）。

它只做一件事：**证明检索没有退化**。不追求优秀，只追求"别人改坏了能拦住"。

运行：
    pytest tests/test_rag_eval_gate.py -q

为什么单独一个文件，不塞进 test_regression_gate.py？
因为评测门禁会随着评测集长大而变长，混在一起会让"跑哪一部分"
变得不清晰。分开之后，CI 可以分别报告两种失败。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.rag_eval import load_cases, retrieval_metrics  # noqa: E402
from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "rag_cases.json"
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

# 当前基线（第 28 章 step2 实测）：recall@5 = 0.90, recall@1 = 0.75
# 门禁比基线略低，留一点噪音余量；任何人把检索改坏到低于它，CI 会红。
MIN_RECALL_AT_5 = 0.85
MIN_RECALL_AT_1 = 0.70


def _index() -> Index:
    idx = Index(embed=hash_embed)
    texts = split_by_heading(DOC, max_chars=400)
    metas = []
    for t in texts:
        m = re.search(r"###\s*(\d+)\.(\d+)", t)
        metas.append({"sections": [f"{m.group(1)}.{m.group(2)}"] if m else []})
    idx.add(texts, metas)
    return idx


def _evaluate() -> dict[int, float]:
    idx = _index()
    cases = load_cases(CASES_PATH)
    hits: dict[int, list[bool]] = {1: [], 3: [], 5: []}
    for case in cases:
        if not case.anchor:
            continue  # 库外问题不参与 L1 评分
        gold = [c.id for c in idx.chunks if case.anchor in c.meta.get("sections", [])]
        got = [c.id for c, _ in idx.search(case.question, k=5)]
        recall, _mrr = retrieval_metrics(got, gold, ks=(1, 3, 5))
        for k in hits:
            hits[k].append(recall[k])
    return {k: sum(v) / len(v) for k, v in hits.items()}


def test_eval_set_is_valid() -> None:
    """评测集本身不能坏：字段齐全、id 唯一、锚点能对上文档小节。"""
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    ids = [c["id"] for c in raw]
    assert len(ids) == len(set(ids)), "评测集里 id 重复了"

    anchors = set(re.findall(r"^###\s*(\d+\.\d+)", DOC, re.MULTILINE))
    for c in raw:
        assert c["question"] and c["ground_truth"] and c["must_contain"], f"{c['id']} 字段不全"
        if c.get("anchor"):
            assert c["anchor"] in anchors, f"{c['id']} 的锚点 {c['anchor']} 不在文档里"


def test_retrieval_recall_gate() -> None:
    """检索质量不能退化：低于门禁就说明有人改坏了分块或嵌入。"""
    got = _evaluate()
    assert got[5] >= MIN_RECALL_AT_5, f"recall@5 退化到 {got[5]:.3f}"
    assert got[1] >= MIN_RECALL_AT_1, f"recall@1 退化到 {got[1]:.3f}"


def test_out_of_scope_cases_exist() -> None:
    """评测集必须保留"库外问题"——否则测不出系统会不会编答案。"""
    cases = load_cases(CASES_PATH)
    out_of_scope = [c for c in cases if "对抗" in c.tags]
    assert len(out_of_scope) >= 2, f"库外问题只剩 {len(out_of_scope)} 条"
    for c in out_of_scope:
        assert "未提及" in c.ground_truth or not c.anchor


@pytest.mark.parametrize("case_id", ["q1", "q5", "q7"])
def test_known_hard_cases_traceable(case_id: str) -> None:
    """难样本必须能被单独定位——排障时不能只有总分。"""
    idx = _index()
    case = next(c for c in load_cases(CASES_PATH) if c.id == case_id)
    gold = [c.id for c in idx.chunks if case.anchor in c.meta.get("sections", [])]
    assert gold, f"{case_id} 的锚点映射不到任何 chunk"
