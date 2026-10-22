"""第 28 章产出：RAG 评测的最小可用框架。

为什么自己写而不直接用 RAGAS？
因为你要先知道"这些指标到底在算什么"，再用 RAGAS（它是把这些算好的封装）。
自己写的版本还有个好处：**没有额外依赖，任何环境都能跑，结果可复现**。

四层指标（从便宜到贵）：
  L1 检索层：recall@k / MRR / hit rate      —— 不需要模型，纯计算
  L2 引用层：引用准确率 / 覆盖率              —— 不需要模型，规则校验
  L3 忠实层：答案是否只基于给定材料          —— 需要 judge
  L4 有用层：答案是否解决了用户问题          —— 需要 judge
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


# ============================================================ 数据模型

@dataclass
class EvalCase:
    id: str
    question: str
    ground_truth: str = ""
    # 答题关键词：答案里必须出现（用于自动判定，不需要 judge）
    must_contain: list[str] = field(default_factory=list)
    # 可接受的同义说法
    alternatives: list[list[str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # 答案锚点：文档里的"第几章第几节"。gold chunk 由它映射，而不是靠文本匹配。
    # 这是"分块策略换了以后评测集还能复用"的关键（第 28 章）。
    anchor: str = ""
    # 样本来源：真实日志 / 人工编写 / 模型生成+人工筛
    source: str = ""


@dataclass
class EvalResult:
    case_id: str
    question: str
    answer: str
    contexts: list[str]
    retrieved_ids: list[str]
    # L1
    recall_at_k: dict[int, bool] = field(default_factory=dict)
    mrr: float = 0.0
    # L2~L4
    contains_required: bool = False
    citation_ok: bool | None = None
    faithfulness: float | None = None
    relevance: float | None = None


def load_cases(path: Path | str) -> list[EvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=r.get("id", str(i)),
            question=r["question"],
            ground_truth=r.get("ground_truth", ""),
            must_contain=r.get("must_contain", []),
            alternatives=r.get("alternatives", []),
            tags=r.get("tags", []),
            anchor=r.get("anchor", ""),
            source=r.get("source", ""),
        )
        for i, r in enumerate(raw)
    ]


def is_out_of_scope(case: EvalCase) -> bool:
    """库外问题（对抗样本）：本来就该拒答，不能算成"检索失败"。"""
    return "库外" in case.tags or "对抗" in case.tags


def kind_of(case: EvalCase) -> str:
    """把样本分成 正例 / 边界 / 对抗 三类，用于切片分析。"""
    if is_out_of_scope(case):
        return "对抗"
    if {"例外", "否定", "边界", "易错", "条件", "多要点", "多跳"} & set(case.tags):
        return "边界"
    return "正例"


# ============================================================ L1 检索指标

def retrieval_metrics(
    retrieved_ids: Sequence[str],
    gold_ids: Sequence[str],
    ks: Sequence[int] = (1, 3, 5),
) -> tuple[dict[int, bool], float]:
    """recall@k 与 MRR。

    注意这里用的是 **chunk id** 而不是文本匹配——
    因为文本会随分块策略变化，而 id 是稳定的。
    这是评测能被复用的前提。
    """
    recall = {k: any(g in retrieved_ids[:k] for g in gold_ids) for k in ks}
    rank = next((i + 1 for i, rid in enumerate(retrieved_ids) if rid in gold_ids), None)
    mrr = 1.0 / rank if rank else 0.0
    return recall, mrr


# ============================================================ L2 引用

def check_citation(answer: str, cited_ids: Sequence[str], valid_ids: set[str]) -> bool:
    """引用校验：答案里引用的 id 必须在真实检索结果里。

    这一层不需要模型，纯规则，能抓住"模型编造来源"这类严重问题。
    这也是最容易被忽略的一层——很多系统的引用是装饰性的。
    """
    if not cited_ids:
        return False
    return all(cid in valid_ids for cid in cited_ids)


def extract_citations(answer: str) -> list[str]:
    """从答案里抽取 [1] / 【c3】 / [c3] 这类引用标记。"""
    return re.findall(r"\[(c?\d+)\]", answer)


# ============================================================ L3/L4 judge

FAITHFULNESS_PROMPT = """判断【答案】里的每一句事实性陈述是否都能在【材料】里找到依据。

只输出 JSON：{{"score": 0.0~1.0, "unsupported": ["没有依据的陈述1", ...]}}

评分标准：
- 1.0：所有事实性陈述都能在材料中找到
- 0.5：一半左右能找到
- 0.0：基本是自己编的

【材料】
{contexts}

【答案】
{answer}"""

RELEVANCE_PROMPT = """判断【答案】是否直接回答了【问题】。

只输出 JSON：{{"score": 0.0~1.0, "reason": "一句话"}}

评分标准：
- 1.0：直接、完整地回答了问题
- 0.5：相关但没正面回答，或漏了关键点
- 0.0：答非所问

【问题】{question}
【答案】{answer}"""


def judge(llm: Any, prompt: str) -> dict:
    raw = llm.invoke(prompt).content
    raw = str(raw).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"score": 0.0, "parse_error": raw[:100]}


def faithfulness_llm(llm: Any, contexts: list[str], answer: str) -> float:
    d = judge(llm, FAITHFULNESS_PROMPT.format(contexts="\n---\n".join(contexts), answer=answer))
    return float(d.get("score", 0.0))


def relevance_llm(llm: Any, question: str, answer: str) -> float:
    d = judge(llm, RELEVANCE_PROMPT.format(question=question, answer=answer))
    return float(d.get("score", 0.0))


# ============================================================ Judge 可靠性校验

def validate_judge(
    llm: Any,
    samples: list[tuple[str, str, float]],
    tolerance: float = 0.3,
) -> dict[str, Any]:
    """校验 judge 靠不靠谱。

    samples: [(contexts, answer, 人工标注分数), ...]

    为什么要做这一步？
    因为 LLM-as-judge 本身也不是可靠的。如果它和人工标注相关性低，
    你所有基于它得出的"优化有效"都是幻觉。
    """
    diffs = []
    for contexts, answer, human in samples:
        if isinstance(contexts, str):
            contexts = [contexts]
        s = faithfulness_llm(llm, contexts, answer)
        diffs.append(abs(s - human))

    agree = sum(1 for d in diffs if d <= tolerance) / max(len(diffs), 1)
    return {
        "n": len(diffs),
        "mean_abs_diff": sum(diffs) / max(len(diffs), 1),
        "agreement_rate": agree,
        "verdict": "可用" if agree >= 0.8 else "不可用，请换 judge 或改 prompt",
    }


# ============================================================ 报表

@dataclass
class Report:
    results: list[EvalResult]

    def summary(self) -> dict[str, Any]:
        n = len(self.results)
        if n == 0:
            return {}

        def avg(vals: list[float]) -> float:
            return sum(vals) / len(vals) if vals else 0.0

        ks = sorted({k for r in self.results for k in r.recall_at_k})
        out: dict[str, Any] = {"n": n}
        for k in ks:
            out[f"recall@{k}"] = avg([1.0 if r.recall_at_k.get(k) else 0.0 for r in self.results])
        out["mrr"] = avg([r.mrr for r in self.results])
        out["answer_contains_required"] = avg([1.0 if r.contains_required else 0.0 for r in self.results])
        cites = [r.citation_ok for r in self.results if r.citation_ok is not None]
        if cites:
            out["citation_ok"] = avg([1.0 if c else 0.0 for c in cites])
        f = [r.faithfulness for r in self.results if r.faithfulness is not None]
        if f:
            out["faithfulness"] = avg(f)
        rl = [r.relevance for r in self.results if r.relevance is not None]
        if rl:
            out["relevance"] = avg(rl)
        return out

    def diff(self, other: "Report") -> dict[str, tuple[float, float, float]]:
        """和另一份报告对比：{指标: (baseline, current, delta)}"""
        a, b = self.summary(), other.summary()
        out = {}
        for k in a:
            if k == "n" or k not in b:
                continue
            out[k] = (a[k], b[k], b[k] - a[k])
        return out

    def failures(self, metric: str = "contains_required") -> list[EvalResult]:
        if metric == "contains_required":
            return [r for r in self.results if not r.contains_required]
        return [r for r in self.results if (getattr(r, metric) or 0) < 0.6]


def print_report(title: str, summary: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(f"样本数：{summary.get('n')}")
    for k, v in summary.items():
        if k == "n":
            continue
        print(f"  {k:<26}{v:>8.3f}")
