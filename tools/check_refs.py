"""引用检查：章号引用、代码路径、相对链接是否真实存在。

运行：
    python tools/check_refs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEMPT = {"OUTLINE.md", "AGENTS.md", "README.md"}


def chapter_files() -> dict[int, Path]:
    out: dict[int, Path] = {}
    for p in ROOT.glob("[0-9][0-9]-*.md"):
        head = p.name[:2]
        if head.isdigit():
            out[int(head)] = p
    return out


def code_dirs() -> set[str]:
    code = ROOT / "code"
    if not code.exists():
        return set()
    return {p.name for p in code.iterdir() if p.is_dir()}


def check(path: Path, chapters: dict[int, Path], cdirs: set[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    # 1. 「第 N 章」引用的章号是否在计划范围内
    #    全书共 41 章（0-40 见 OUTLINE.md）。未写出的章允许被引用，
    #    超出范围的章号视为错误。
    for m in re.finditer(r"第\s*(\d{1,2})\s*章", text):
        n = int(m.group(1))
        if n > 41:
            problems.append(f"引用了超出范围的第 {n} 章（全书共 41 章）")

    # 2. code/chXX_* 路径是否存在对应目录
    for m in re.finditer(r"code/(ch\d{2}_[a-z0-9_]+)", text):
        name = m.group(1)
        if name not in cdirs:
            problems.append(f"引用了不存在的代码目录：code/{name}")

    # 3. 代码目录编号应与所在章一致
    own = path.name[:2]
    if own.isdigit():
        for m in re.finditer(r"code/ch(\d{2})_", text):
            if m.group(1) != own:
                problems.append(f"代码目录编号 ch{m.group(1)} 与本章 {own} 不一致")

    # 4. 相对链接
    for m in re.finditer(r"\]\(([^)#][^)]*)\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (ROOT / target).exists():
            problems.append(f"坏链：{target}")

    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    chapters = chapter_files()
    cdirs = code_dirs()

    files = sorted(p for p in ROOT.glob("*.md") if p.name not in EXEMPT)
    total = 0
    for p in files:
        probs = check(p, chapters, cdirs)
        if probs:
            total += len(probs)
            print(f"\n{p.name}")
            for x in probs:
                print(f"  - {x}")

    if total:
        print(f"\n共 {total} 个问题。")
        return 1

    print(f"检查 {len(files)} 个文件，引用均有效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
