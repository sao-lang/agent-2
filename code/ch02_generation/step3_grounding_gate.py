"""第 2 章 step3：依据强度判定器（离线可运行）。

运行：
    python code/ch02_generation/step3_grounding_gate.py

演示在调用模型之前，用关键词覆盖情况判定依据强度，
并据档位决定是否调用模型、以及如何组织对外返回。
不调用真实模型。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import Enum


class Grounding(Enum):
    STRONG = "有依据"
    WEAK = "弱依据"
    NONE = "无依据"


@dataclass
class Verdict:
    level: Grounding
    hits: int
    reason: str

    @property
    def can_answer(self) -> bool:
        return self.level is Grounding.STRONG


STOPWORDS = {"的", "了", "吗", "呢", "是", "在", "有", "和", "就", "都"}


def keywords(question: str) -> set[str]:
    """粗切关键词。中文按相邻两字切分，去掉高频虚词。"""
    chars = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", question)
    bigrams = {chars[i : i + 2] for i in range(len(chars) - 1)}
    return {w for w in bigrams if w not in STOPWORDS}


def judge(question: str, contexts: list[str]) -> Verdict:
    """判定依据强度。"""
    if not contexts:
        return Verdict(Grounding.NONE, 0, "检索结果为空")

    q = keywords(question)
    if not q:
        return Verdict(Grounding.WEAK, 0, "提问无法提取关键词")

    joined = "".join(contexts)
    hit = {w for w in q if w in joined}
    ratio = len(hit) / len(q)

    if ratio >= 0.5:
        return Verdict(Grounding.STRONG, len(hit), f"关键词覆盖 {ratio:.0%}")
    return Verdict(Grounding.WEAK, len(hit), f"关键词覆盖 {ratio:.0%}，低于一半")


def respond(verdict: Verdict, answer: str) -> str:
    """按依据强度决定对外返回什么。"""
    if verdict.level is Grounding.STRONG:
        return answer
    if verdict.level is Grounding.WEAK:
        return f"{answer}\n\n（依据不足，以上内容可能需要核实）"
    return "这个问题我无法根据现有资料确认，建议转人工处理。"


DOC = "签收后七天内可以申请无理由退货。定制类商品不适用无理由退货。"

CASES = [
    ("签收后多久可以退货？", [DOC]),
    ("已激活的耳机能退吗？", [DOC]),
    ("退货运费谁承担？", []),
]


def main() -> None:
    print("=" * 84)
    print("① 三档判定")
    print("=" * 84)
    print(f"  {'提问':<22}{'依据':<8}{'判定':<8}{'命中':<6}{'覆盖说明'}")
    print("  " + "-" * 80)
    verdicts = []
    for q, ctx in CASES:
        v = judge(q, ctx)
        verdicts.append((q, ctx, v))
        print(f"  {q:<22}{('有' if ctx else '空'):<8}{v.level.value:<8}"
              f"{v.hits:<6}{v.reason}")

    print()
    print("=" * 84)
    print("② 按档位决定处理方式")
    print("=" * 84)
    print(f"  {'提问':<22}{'调用模型':<10}{'对外返回'}")
    print("  " + "-" * 80)
    for q, ctx, v in verdicts:
        called = "是" if v.level is not Grounding.NONE else "否"
        if v.level is Grounding.NONE:
            out = respond(v, "")
        else:
            out = respond(v, "（模型回答）")
        out = out.replace("\n\n", " / ")
        print(f"  {q:<22}{called:<10}{out}")

    print()
    print("=" * 84)
    print("③ 结论")
    print("=" * 84)
    print("  1. 无依据时不调用模型，直接兜底")
    print("  2. 弱依据仍调用模型，但输出附带核实提示")
    print("  3. 只有强依据的输出可直接使用")
    print("  4. 判定发生在调用之前，不依赖模型自评")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
