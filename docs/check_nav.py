#!/usr/bin/env python3
"""全书导航自检：book.json、章首六行、章末导航、文件名、INDEX.md、相对链接、章号引用。

用法：
    python docs/check_nav.py
    python docs/check_nav.py --quiet     # 只报问题

它在 `python docs/gen_book.py build` 之后运行；任何一条不过都返回非零。
检查项与 docs/WRITING-SPEC.md 第 1.4 节、OUTLINE.md 的全局不变量一一对应。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_book import (  # noqa: E402
    ROOT,
    fname,
    load,
    nav_line,
    norm_title,
    point_line,
    render_index,
    vol_line,
)

MAX_CHAPTER = 57


def check_book(data: dict) -> list[str]:
    bad: list[str] = []
    nos = [c["no"] for c in data["chapters"]]
    if nos != list(range(len(nos))):
        bad.append("book.json：章号不是从 0 开始的连续整数")
    vols: dict[int, int] = {}
    for v in data["volumes"]:
        for no in v["chapters"]:
            if no in vols:
                bad.append(f"book.json：第 {no} 章同时属于卷 {vols[no]} 与卷 {v['no']}")
            vols[no] = v["no"]
    for no in nos:
        if no not in vols:
            bad.append(f"book.json：第 {no} 章没有归属卷")
    if len(nos) != data["chapters_total"]:
        bad.append(f"book.json：chapters_total={data['chapters_total']}，实际 {len(nos)} 章")
    ids = [p["id"] for p in data["points"]]
    if len(ids) != len(set(ids)):
        bad.append("book.json：知识点编号有重复")
    if len(ids) != data["points_total"]:
        bad.append(f"book.json：points_total={data['points_total']}，实际 {len(ids)} 条")
    for ch in data["chapters"]:
        for pid in ch["points"]:
            if pid not in data["_point"]:
                bad.append(f"book.json：第 {ch['no']} 章引用了不存在知识点 {pid}")
    return bad


def check_chapter(ch: dict, data: dict) -> list[str]:
    bad: list[str] = []
    path = ROOT / fname(ch)
    if not path.exists():
        return [f"第 {ch['no']} 章：文件不存在或命名不符，应为 {fname(ch)}"]
    text = path.read_text(encoding="utf-8")
    lines = text.replace("\r\n", "\n").split("\n")
    head = lines[0]
    expect_h1 = f"# 第 {ch['no']} 章 · {ch['title']}"
    if norm_title(head) != norm_title(expect_h1):
        bad.append(f"{path.name}：H1 与 book.json 不一致\n    实际 {head}\n    应为 {expect_h1}")
    if vol_line(ch, data) not in text:
        bad.append(f"{path.name}：章首卷行缺失或已过期（跑 gen_book.py build）")
    if point_line(ch, data) not in text:
        bad.append(f"{path.name}：章首知识点行缺失或与 book.json 不一致")
    if nav_line(ch, data) not in text:
        bad.append(f"{path.name}：章末导航行缺失或与 book.json 不一致")
    for key in ("**本章回答**", "**示例目录**", "**读完应当能回答**"):
        if key not in "\n".join(lines[:12]):
            bad.append(f"{path.name}：章首缺少 {key}")
    if "## 下一章" not in text:
        bad.append(f"{path.name}：缺少「## 下一章」")
    return bad


def check_files(data: dict) -> list[str]:
    bad: list[str] = []
    done = {fname(c) for c in data["chapters"] if c["status"] == "done"}
    found = {p.name for p in ROOT.glob("[0-9][0-9]-*.md")}
    for name in sorted(found - done):
        bad.append(f"多余章节文件（book.json 里没有）：{name}")
    for name in sorted(done - found):
        bad.append(f"缺少章节文件：{name}")
    return bad


def check_index(data: dict) -> list[str]:
    path = ROOT / "INDEX.md"
    if not path.exists():
        return ["INDEX.md 不存在（跑 python docs/gen_book.py index）"]
    if path.read_text(encoding="utf-8") != render_index(data):
        return ["INDEX.md 与 book.json 不同步（跑 python docs/gen_book.py index）"]
    return []


def check_links(paths: list[Path]) -> list[str]:
    bad: list[str] = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)   # 代码块里的示例链接不算
        text = re.sub(r"`[^`\n]*`", "", text)               # 行内代码里的示例链接不算
        for target in re.findall(r"\]\((\./[^)\s]+)\)", text):
            if "#" in target:
                target = target.split("#", 1)[0]
            if not target:
                continue
            if not (p.parent / target[2:]).exists():
                bad.append(f"{p.relative_to(ROOT)}：相对链接指向不存在的文件 {target}")
    return bad


def check_chapter_refs(paths: list[Path]) -> list[str]:
    bad: list[str] = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        for num in re.findall(r"第 (\d{1,2}) 章", text):
            if not 0 <= int(num) <= MAX_CHAPTER:
                bad.append(f"{p.name}：章号引用越界「第 {num} 章」")
    return bad


def main(argv: list[str]) -> int:
    data = load()
    quiet = "--quiet" in argv
    problems: list[str] = []
    problems += check_book(data)
    problems += check_files(data)
    for ch in data["chapters"]:
        if ch["status"] == "done":
            problems += check_chapter(ch, data)
    problems += check_index(data)

    scope = [p for p in ROOT.glob("[0-9][0-9]-*.md")]
    scope += [ROOT / "INDEX.md", ROOT / "README.md", ROOT / "OUTLINE.md", ROOT / "book.json"]
    scope += list((ROOT / "outline").glob("*.md")) + list((ROOT / "docs").glob("*.md"))
    scope = [p for p in scope if p.exists()]
    problems += check_links([p for p in scope if p.suffix == ".md"])
    problems += check_chapter_refs(scope)

    if problems:
        print(f"FAIL  {len(problems)} 项不通过：")
        for item in problems:
            print("  - " + item)
        return 1

    done = sum(1 for c in data["chapters"] if c["status"] == "done")
    if not quiet:
        print(f"OK    {done}/{len(data['chapters'])} 章已写；"
              f"卷 {len(data['volumes'])} 个、知识点 {len(data['points'])} 条；"
              "章首/章末/文件名/INDEX/相对链接全部一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
