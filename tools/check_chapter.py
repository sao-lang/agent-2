"""章节结构检查：对照 docs/WRITING-SPEC.md 第三节。

运行：
    python tools/check_chapter.py          # 检查全部章节
    python tools/check_chapter.py 05       # 只检查指定章

检查项：
    1. 章首四行元信息齐全且顺序正确
    2. 小结与下一章两个收尾小节存在
    3. 标题不得使用比喻式冒号结构

正文的小节划分、数量、先后顺序由内容决定，不做检查。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEMPT = {0}

# 章首四行的字段名，顺序固定
HEADER_FIELDS = ["知识点", "交付", "组件", "读完应当能回答"]

# 收尾两个小节必须存在
REQUIRED_SECTIONS = [
    ("这一章建立的", "小结"),
    ("下一章", "衔接"),
]

# 标题里不允许的比喻式冒号用法
BANNED_TITLE_PATTERN = re.compile(r"^\d+\.\d+\s*\S{2,8}：|\S{2,6}：.*")


def chapter_no(path: Path) -> int | None:
    head = path.name[:2]
    return int(head) if head.isdigit() and path.name[2] == "-" else None


def split_outside_fence(text: str) -> list[tuple[int, str]]:
    """返回 (行号, 行内容)，跳过围栏代码块内部。"""
    out = []
    in_fence = False
    for i, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((i, line))
    return out


def check_header(lines: list[tuple[int, str]], problems: list[str]) -> None:
    header = [l for _, l in lines[:10] if l.startswith("> **")]
    found = []
    for l in header:
        m = re.match(r"> \*\*(.+?)\*\*：", l)
        if m:
            found.append(m.group(1))

    missing = [f for f in HEADER_FIELDS if f not in found]
    if missing:
        problems.append(f"章首缺少元信息：{'、'.join(missing)}")
        return

    order = [f for f in found if f in HEADER_FIELDS]
    if order != HEADER_FIELDS:
        problems.append(f"章首元信息顺序应为 {' → '.join(HEADER_FIELDS)}，实际为 {' → '.join(order)}")


def check_title_matches_filename(path: Path, lines: list[tuple[int, str]], problems: list[str]) -> None:
    """章节标题必须与文件名一致（去掉编号前缀后逐字相同）。"""
    h1 = [l for _, l in lines if l.startswith("# ")]
    if not h1:
        problems.append("缺少一级标题")
        return
    title = h1[0][2:].strip()
    stem = path.stem  # 01-一次调用的完整链路
    expected = stem.split("-", 1)[1] if "-" in stem else stem
    # 标题形如「第 1 章 一次调用的完整链路」
    m = re.match(r"^第\s*\d+\s*章\s*(.+)$", title)
    actual = m.group(1).strip() if m else title
    if actual != expected:
        problems.append(f"标题与文件名不一致：标题「{actual}」，文件名「{expected}」")


def check_sections(lines: list[tuple[int, str]], no: int, problems: list[str]) -> None:
    """只检查收尾小节存在与标题写法；正文小节如何划分不干预。"""
    h2 = [(i, l) for i, l in lines if l.startswith("## ")]
    if not h2:
        problems.append("没有任何二级标题")
        return

    for i, l in h2:
        title = l[3:].strip()
        m = re.match(rf"^{no}\.(\d+)\s", title)
        if m and BANNED_TITLE_PATTERN.match(title) and "：" in title:
            left = title.split("：")[0]
            if len(left.replace(f"{no}.{m.group(1)}", "").strip()) <= 8:
                problems.append(f"第 {i} 行标题疑似比喻式结构，应改为对象或结论：{title}")

    joined = "\n".join(l for _, l in h2)
    for key, name in REQUIRED_SECTIONS:
        if key not in joined:
            problems.append(f"缺少必需小节：{name}（标题含「{key}」）")


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    no = chapter_no(path)
    problems: list[str] = []
    if no is None or no in EXEMPT:
        return problems

    lines = split_outside_fence(text)
    check_header(lines, problems)
    check_title_matches_filename(path, lines, problems)
    check_sections(lines, no, problems)
    return problems


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    only = {n.zfill(2) for n in argv[1:]}
    files = sorted(p for p in ROOT.glob("[0-9][0-9]-*.md"))
    if only:
        files = [p for p in files if p.name[:2] in only]

    total = 0
    for p in files:
        probs = check(p)
        if probs:
            total += len(probs)
            print(f"\n{p.name}")
            for x in probs:
                print(f"  - {x}")

    if total:
        print(f"\n共 {total} 个问题。")
        return 1
    print(f"检查 {len(files)} 个文件，结构通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
