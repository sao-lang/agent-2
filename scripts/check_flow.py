#!/usr/bin/env python3
"""连贯性检查：抓"压缩之后前后文断裂"的问题。

与另外两个检查器的分工：
    lint_prose.py       话难听（AI 味）
    check_reader.py     话不完整（代码/输出/并列项/术语 的锚点）
    check_flow.py       话接不上（指代没有先行词、结论指向被删的表格/小节、空节）

四类：
    F1 孤儿指代     段落以"这/那/它/该/此/前者/后者/后果/结果"开头，
                    但与上一段没有任何汉字二元组重合（说明先行词被删了）
    F2 指向被删的表格 "表格后两行/上表/下表/第三行" 之类，但紧邻上方不是表格
    F3 指向被删的小节 "上一节/前一节/上面那节" 但本节之前没有对应小节
    F4 空壳小节     标题下直接是代码块或结论，没有一句总起

用法：
    python scripts/check_flow.py 01 02 ...
    python scripts/check_flow.py --all
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REF_OPEN = ("这", "那", "它", "该", "此", "前者", "后者", "后果", "结果", "由此", "于是")
TABLE_REF = re.compile(r"表格[后前]|上表|下表|第三行|第二行|后两行|前两行|这一行")
SECTION_REF = re.compile(r"上一节|前一节|上面那节|上一小节|前面那节")
HAN = re.compile(r"[\u4e00-\u9fff]")


def blocks(text: str):
    """按块返回 (类型, 行号, 文本)：heading / table / fence / para"""
    lines = text.replace("\r\n", "\n").split("\n")
    out, in_f, start = [], False, 0
    buf, bstart = [], 0

    def flush():
        nonlocal buf
        if buf:
            out.append(("para", bstart, "\n".join(buf)))
            buf = []

    for i, l in enumerate(lines, 1):
        s = l.strip()
        if s.startswith("```"):
            if not in_f:
                flush()
                in_f, start = True, i
            else:
                in_f = False
                out.append(("fence", start, ""))
            continue
        if in_f:
            continue
        if re.match(r"^#{1,6} ", s):
            flush()
            out.append(("heading", i, s))
            continue
        if s.startswith("|"):
            flush()
            out.append(("table", i, s))
            continue
        if not s:
            flush()
            bstart = i + 1
            continue
        if s.startswith(">"):
            flush()
            continue
        if not buf:
            bstart = i
        buf.append(l)
    flush()
    return out


def bigrams(s: str) -> set[str]:
    h = "".join(HAN.findall(s))
    return {h[i:i + 2] for i in range(len(h) - 1)}


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    bs = blocks(text)
    bad = []

    for idx, (kind, ln, body) in enumerate(bs):
        if kind == "table":
            continue
        if kind == "heading":
            # F4：标题后紧跟代码块（本节没有总起句）
            nxt = bs[idx + 1] if idx + 1 < len(bs) else None
            if nxt and nxt[0] == "fence" and body.startswith("###"):
                bad.append(f"L{ln} F4 空壳小节：{body[:24]} 标题后直接是代码块")
            continue
        if kind != "para":
            continue

        head = body.strip()[:26]
        # 找上一段（跳过标题）
        prev = None
        for k in range(idx - 1, -1, -1):
            if bs[k][0] == "para":
                prev = bs[k]
                break
            if bs[k][0] == "heading":
                break

        # F1 孤儿指代
        if head.startswith(REF_OPEN):
            if prev is None:
                bad.append(f"L{ln} F1 孤儿指代（本节无上段）：{head[:22]}")
            else:
                shared = bigrams(prev[2]) & bigrams(head)
                if not shared:
                    bad.append(f"L{ln} F1 孤儿指代（与上段无共同词）：{head[:22]}")

        # F5 结论里出现"首次登场"的新说法（定义它的段落被删了）
        quoted = re.findall(r"[“\"]([^”\"]{2,12})[”\"]", body)
        if quoted and re.search(r"后果|结果|因此|所以|这说明|意味着", body):
            seen_before = "".join(b[2] for b in bs[:idx] if b[0] == "para")
            for q in quoted:
                if q not in seen_before:
                    bad.append(f"L{ln} F5 结论引用了未定义的说法：「{q}」（前文从未出现）")
                    break

        # F2 指向被删的表格
        if TABLE_REF.search(head):
            above = [b for b in bs[:idx] if b[0] in ("table", "para")]
            if not above or above[-1][0] != "table":
                bad.append(f"L{ln} F2 指向已不存在的表格：{head[:22]}")

        # F3 指向被删的小节
        if SECTION_REF.search(head):
            prev_heads = [b[2] for b in bs[:idx] if b[0] == "heading" and b[2].startswith("###")]
            if len(prev_heads) < 2:
                bad.append(f"L{ln} F3 指向不存在的小节：{head[:22]}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    files = sorted(p for p in ROOT.glob("*.md") if re.match(r"^\d{2}-", p.name))
    if args.stems:
        files = [f for f in files if f.name[:2] in args.stems]

    total = 0
    print(f"{'章':<4}{'F1':>4}{'F2':>4}{'F3':>4}{'F4':>4}{'合计':>6}")
    for f in files:
        issues = check(f)
        total += len(issues)
        c = {k: sum(1 for x in issues if f" {k} " in x) for k in ("F1", "F2", "F3", "F4", "F5")}
        if issues or not args.quiet:
            print(f"{f.name[:2]:<4}{c['F1']:>4}{c['F2']:>4}{c['F3']:>4}{c['F4']:>4}{c['F5']:>4}{len(issues):>6}")
        if issues and not args.quiet:
            for it in issues[:10]:
                print(f"     {it}")
    print(f"\n合计问题 {total} 条")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
