"""第 29 章 step1：先给评测集做体检（离线，不花钱）。

运行：
    python code/ch41_eval/rag_step1_eval_set_check.py

上一级的痛点：没有（这是起点）。
这一级做什么：在你相信任何"指标"之前，先证明**评测集本身是健康的**。

体检四件事：
  1. 字段完整性 —— 缺 anchor 的样本，换个分块策略就没法判分了
  2. 重复检测   —— 同一个问题问三遍，会让指标虚高
  3. 标签分布   —— 只有"简单题"的评测集，测不出系统上限
  4. 难度分层   —— 正例 / 边界 / 对抗 三类各占多少

判断标准写在代码里的 MIN_* 常量，你可以按自己的业务改。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "evals" / "rag_cases.json"

# 体检阈值：低于这些值，说明评测集还不能用
MIN_SAMPLES = 20
MIN_PER_TAG = 2
MAX_DUP_RATIO = 0.0  # 一条重复都不允许


def load() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def check_fields(cases: list[dict]) -> list[str]:
    """字段完整性：缺一个字段，就有一条样本废掉。"""
    problems = []
    for c in cases:
        cid = c.get("id", "?")
        if not c.get("question"):
            problems.append(f"{cid} 缺 question")
        if not c.get("ground_truth"):
            problems.append(f"{cid} 缺 ground_truth（人写的标准答案）")
        if not c.get("must_contain"):
            problems.append(f"{cid} 缺 must_contain（自动判分的关键词）")
        if not c.get("anchor") and not {"库外", "对抗"} & set(c.get("tags", [])):
            problems.append(f"{cid} 缺 anchor（答案在文档的第几节）")
    return problems


def check_duplicates(cases: list[dict]) -> tuple[list[str], float]:
    """重复检测：问题文本重复 = 重复计分。"""
    norm = [c["question"].strip().replace("？", "").replace("?", "") for c in cases]
    dup_ids: list[str] = []
    for q, n in Counter(norm).items():
        if n > 1:
            ids = [c["id"] for c, x in zip(cases, norm) if x == q]
            dup_ids.append(f"问题重复：{'/'.join(ids)} -> {q}")
    return dup_ids, len(dup_ids) / max(len(cases), 1)


def classify(case: dict) -> str:
    """把样本分成 正例 / 边界 / 对抗 三类。

    这是评测集最重要的一个设计决策：
      · 正例：正常提问，系统本该答对
      · 边界：容易答错但又很常见（否定、例外、条件、多要点）
      · 对抗：故意问库里没有的东西，系统本该拒答
    只有正例的评测集，会把"什么都敢答"的模型评成满分。
    """
    tags = set(case.get("tags", []))
    if {"库外", "对抗"} & tags:
        return "对抗"
    if tags & {"例外", "否定", "边界", "易错", "条件", "多要点", "多跳"}:
        return "边界"
    return "正例"


def main() -> None:
    cases = load()
    print("=" * 74)
    print("评测集体检报告")
    print("=" * 74)
    print(f"文件：{CASES_PATH.relative_to(ROOT)}")
    print(f"样本数：{len(cases)}")

    problems = check_fields(cases)
    dups, dup_ratio = check_duplicates(cases)
    tags = Counter(t for c in cases for t in c.get("tags", []))
    kinds = Counter(classify(c) for c in cases)

    print("\n① 字段完整性")
    if problems:
        for p in problems:
            print(f"   [x] {p}")
    else:
        print("   [v] question / ground_truth / must_contain / anchor 全齐")

    print("\n② 重复检测")
    if dups:
        for d in dups:
            print(f"   [x] {d}")
    else:
        print("   [v] 没有重复问题")

    print("\n③ 标签分布")
    for t, n in tags.most_common():
        flag = "[v]" if n >= MIN_PER_TAG else "[x] 样本太少，这一类的结论不可信"
        print(f"   {t:<8}{n:>3}  {flag}")

    print("\n④ 难度分层（正例 / 边界 / 对抗）")
    for k in ("正例", "边界", "对抗"):
        n = kinds.get(k, 0)
        print(f"   {k:<6}{n:>3}  {n / len(cases):>5.0%}")

    print("\n" + "=" * 74)
    print("结论")
    print("=" * 74)
    verdict = []
    if len(cases) < MIN_SAMPLES:
        verdict.append(f"样本数 {len(cases)} < {MIN_SAMPLES}：指标只能证明流程跑通，不能用来下结论")
    if dup_ratio > MAX_DUP_RATIO:
        verdict.append("存在重复样本：指标会虚高")
    if kinds.get("对抗", 0) == 0:
        verdict.append("没有『库外问题』：你测不出系统会不会编答案（RAG 最严重的失败）")
    if kinds.get("边界", 0) / len(cases) < 0.2:
        verdict.append("边界样本 < 20%：评测集偏简单，测不出真实上限")

    if verdict:
        for v in verdict:
            print(f"   [x] {v}")
    else:
        print("   [v] 体检通过，可以开始跑基线")
        print("\n   注意：『通过』只代表**这份评测集自己没毛病**，")
        print("   不代表 20 条出头就够用了——样本量的问题，要等到做决策时才算数。")


if __name__ == "__main__":
    main()
