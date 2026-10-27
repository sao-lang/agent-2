"""PII 遮罩：正则的匹配顺序，以及"顺序"之外的根因。

不联网。四种写法跑同一段文本：
  A 朴素正则，先遮手机号
  B 朴素正则，先遮身份证
  C 加边界断言，先遮手机号
  D 加边界断言，先遮身份证

遮罩函数保持长度不变，所以匹配的位置可以直接当作原文位置来统计：
每个敏感值被遮住了多少位、手机号里有几条其实是身份证的碎片。
"""

from __future__ import annotations

import re

TEXT = "身份证 110101199003078515，联系电话 13812345678，备用号 15900001111。"
ID_VALUE = "110101199003078515"
PHONES = ["13812345678", "15900001111"]
SENSITIVE = [("身份证", ID_VALUE), ("手机号甲", PHONES[0]), ("手机号乙", PHONES[1])]

NAIVE_ID = re.compile(r"\d{17}[\dXx]")
NAIVE_PHONE = re.compile(r"1[3-9]\d{9}")

# (?<!\d) / (?!\d) 是边界断言：左右两侧不能还是数字
GUARDED_ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
GUARDED_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def mask_id(m: re.Match) -> str:
    s = m.group()
    return "*" * (len(s) - 4) + s[-4:]


def mask_phone(m: re.Match) -> str:
    s = m.group()
    return s[:3] + "****" + s[-4:]


def run(text: str, id_pat: re.Pattern, phone_pat: re.Pattern,
        phone_first: bool) -> tuple[str, list[tuple[str, int, int]]]:
    """返回遮罩后的文本与事件表。遮罩等长，事件位置就是原文位置。"""
    events: list[tuple[str, int, int]] = []

    def make(kind: str):
        def repl(m: re.Match) -> str:
            events.append((kind, m.start(), m.end()))
            return mask_id(m) if kind == "id" else mask_phone(m)
        return repl

    steps = [("phone", phone_pat, make("phone")), ("id", id_pat, make("id"))]
    if not phone_first:
        steps.reverse()
    out = text
    for _, pat, repl in steps:
        out = pat.sub(repl, out)
    return out, events


def span_of(value: str) -> tuple[int, int]:
    start = TEXT.index(value)
    return start, start + len(value)


def overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def main() -> None:
    print("=== 0. 原文 ===")
    print(f"  {TEXT}")

    plans = [
        ("A 朴素，手机号先", NAIVE_ID, NAIVE_PHONE, True),
        ("B 朴素，身份证先", NAIVE_ID, NAIVE_PHONE, False),
        ("C 边界断言，手机号先", GUARDED_ID, GUARDED_PHONE, True),
        ("D 边界断言，身份证先", GUARDED_ID, GUARDED_PHONE, False),
    ]

    print()
    print("=== 1. 四种写法的结果 ===")
    for label, id_pat, phone_pat, phone_first in plans:
        out, events = run(TEXT, id_pat, phone_pat, phone_first)
        n_id = sum(1 for k, _, _ in events if k == "id")
        phone_spans = [(s, e) for k, s, e in events if k == "phone"]
        id_span = span_of(ID_VALUE)
        fake = sum(1 for s, e in phone_spans if overlap((s, e), id_span))
        by_id = {p for k, s, e in events if k == "id" for p in range(s, e)}
        by_phone = {p for k, s, e in events if k == "phone" for p in range(s, e)}
        covered = sum(1 for p in range(*id_span) if p in by_id or p in by_phone)
        starred = sum(1 for p in range(*id_span) if out[p] == "*")
        visible = sum(1 for p in range(*id_span)
                      if TEXT[p].isdigit() and out[p].isdigit())
        print(f"  {label}")
        print(f"    检出：身份证 {n_id} 条，手机号 {len(phone_spans)} 条"
              f"（其中 {fake} 条与身份证位置重叠）")
        print(f"    身份证：规则命中 {covered} 位、换成 * {starred} 位，"
              f"仍明文可见 {visible} / {len(ID_VALUE)} 位")
        print(f"    结果：{out}")
        print()

    print("=== 2. A 的漏检是怎么发生的 ===")
    m = NAIVE_PHONE.search(TEXT)
    start = span_of(ID_VALUE)[0]
    print(f"  身份证从第 {start} 个字符开始")
    print(f"  手机号正则第一个匹配：位置 {m.start()}-{m.end()}，内容 {m.group()}")
    print(f"  它落在身份证内部第 {m.start() - start} 位起的 11 个字符上")
    out_a, _ = run(TEXT, NAIVE_ID, NAIVE_PHONE, True)
    print(f"  遮完之后还能匹配到 {len(NAIVE_ID.findall(out_a))} 条身份证")
    print("  <- 手机号正则先吃掉了身份证中间 11 位，身份证正则再也匹配不上")

    print()
    print("=== 3. 边界断言修掉的是根因 ===")
    print(f"  朴素手机号正则的匹配位置：{[m.start() for m in NAIVE_PHONE.finditer(TEXT)]}")
    print(f"  加断言的匹配位置：        {[m.start() for m in GUARDED_PHONE.finditer(TEXT)]}")
    print("  <- 位置 10 那一处不再匹配，顺序就不重要了")


if __name__ == "__main__":
    main()
