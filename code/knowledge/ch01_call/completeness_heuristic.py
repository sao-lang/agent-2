"""为什么不能用"结尾有没有句号"判断文本是否完整。

不联网。构造一批真实会出现的结尾，逐个检查两种判断方法。
"""

from __future__ import annotations

from dataclasses import dataclass

STOP_MARKS = ("。", "！", "？", ".", "!", "?", "\n")

# 每种结尾都可能在 length 或 stop 下出现，标注是为了说明判断方法的局限
CASES = [
    ("签收后 7 天内可退。", "stop", "正常完整"),
    ("签收后 7 天内可退。", "length", "刚好在句号处被掐断"),
    ("签收后 7 天内", "length", "半句话"),
    ("签收后 7 天内可退，条件是商品", "length", "半句话"),
    ("可以。", "length", "短答案，被掐在完整句之后"),
    ("①", "stop", "模型输出结束标记，但内容是列表符号"),
    ("", "content_filter", "空"),
]


@dataclass
class Case:
    text: str
    reason: str
    note: str


def looks_complete(text: str) -> bool:
    """启发式方法：结尾是标点就当完整。"""
    if not text:
        return False
    return text.rstrip()[-1] in STOP_MARKS


def main() -> None:
    rows: list[Case] = [Case(t, r, n) for t, r, n in CASES]

    print(f"{'结尾':<34}{'finish_reason':<15}{'标点法':<8}{'说明'}")
    print("-" * 92)
    for c in rows:
        guess = "完整" if looks_complete(c.text) else "不完整"
        print(f"{c.text!r:<34}{c.reason:<15}{guess:<8}{c.note}")

    print()
    wrong = [
        c for c in rows
        if (looks_complete(c.text) and c.reason != "stop")
        or (not looks_complete(c.text) and c.reason == "stop")
    ]
    print(f"标点法与 finish_reason 不一致的：{len(wrong)} / {len(rows)}")
    for c in wrong:
        print(f"  {c.text!r:<34} finish_reason={c.reason:<15} {c.note}")

    print()
    print("第一行与第二行文本完全相同，finish_reason 不同。")
    print("只看文本，无法区分这两种情况。")


if __name__ == "__main__":
    main()
