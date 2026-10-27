"""三种依据强度：有依据、弱依据、无依据。

不联网。用一个查表式的假后端演示"答案从哪来"：
同一个问题，给不给资料，返回内容的性质完全不同。

这里演示的是"依据的有无如何影响输出"，不是模型的实际行为。
"""

from __future__ import annotations

from dataclasses import dataclass

DOCS = {"退货期限": "商品签收后 7 天内可申请退货，需保持商品完好。"}
QUESTION = "退货期限是多久？"


@dataclass
class Answer:
    text: str
    evidence: str
    sourced_from: str | None


def answer_with_docs(question: str, docs: dict[str, str]) -> Answer:
    """有直接依据：资料里就有答案。"""
    if "退货期限" in docs:
        return Answer(docs["退货期限"], "strong", "退货期限")
    return answer_without_docs(question)


def answer_with_partial(question: str, docs: dict[str, str]) -> Answer:
    """弱依据：资料相关，但没写具体数值。"""
    related = [v for k, v in docs.items() if "退" in k or "退" in v]
    if related:
        return Answer(
            f"{related[0]}（具体天数需要确认）",
            "weak",
            "部分相关",
        )
    return answer_without_docs(question)


def answer_without_docs(question: str) -> Answer:
    """无依据：资料里没有，只能靠训练时见过的东西拼。"""
    return Answer(
        "商品签收后 7 天内可申请退货，通常需保持商品完好并保留发票。",
        "none",
        None,
    )


def main() -> None:
    print(f"问题：{QUESTION}")
    print(f"可信资料：{DOCS['退货期限']}")
    print()

    cases = [
        ("有依据", answer_with_docs(QUESTION, DOCS)),
        ("弱依据", answer_with_partial(QUESTION, {"退货": "本店支持退货"})),
        ("无依据", answer_without_docs(QUESTION)),
    ]

    for label, ans in cases:
        print(f"=== {label} ===")
        print(f"  回答：{ans.text}")
        print(f"  依据强度：{ans.evidence}")
        print(f"  来源：{ans.sourced_from}")
        print()

    print("三种情况下的差别：")
    print("  有依据：答案的字面来自资料，可以逐字核对。")
    print("  弱依据：资料只说了存在性，数值是补上去的，无法核对。")
    print("  无依据：没有任何来源，但输出形式和有依据时完全一样。")
    print()
    print("关键：三种情况的输出格式没有区别，")
    print("      只能靠调用方记录来源，事后才分得清。")


if __name__ == "__main__":
    main()
