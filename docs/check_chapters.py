"""章节自检：结构、篇幅、表格、章号引用。

用法：
    python docs/check_chapters.py 22-编排的三层.md [更多文件...]
    python docs/check_chapters.py --all        # 检查仓库根目录的 00-*.md … 26-*.md

检查项（对应 docs/WRITING-SPEC.md 与 outline/ 的约定）：
  1. 章首四行元信息齐全（知识点 / 本章回答 / 示例目录 / 读完应当能回答）
  2. 有「这一章建立的 N 件事」，且 N 与条目数一致
  3. 有「下一章」
  4. 中文字符数（不含代码块与表格）不低于 9000
  5. Markdown 表格列数一致（转义竖线不计）
  6. 二级标题中文不超过 12 字
  7. 「第 N 章」引用不超出 0–59
  8. 代码块成对
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_CHARS = 9000          # 目标 10000+，不设上限（见 WRITING-SPEC 第二节）


def chinese_chars(text: str) -> int:
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    body = re.sub(r"^\|.*$", "", body, flags=re.M)
    return len(re.findall(r"[\u4e00-\u9fff]", body))


def check_table_pipes(lines: list[str]) -> list[str]:
    problems: list[str] = []
    block: list[str] = []
    start = 0

    def flush(b: list[str], s: int) -> None:
        if len(b) < 2:
            return
        counts = {len(re.findall(r"(?<!\\)\|", line)) for line in b}
        if len(counts) > 1:
            problems.append(f"  L{s}: 表格列数不一致 {sorted(counts)}")

    for i, line in enumerate(lines, 1):
        if line.strip().startswith("|"):
            if not block:
                start = i
            block.append(line)
        else:
            flush(block, start)
            block = []
    flush(block, start)
    return problems


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    issues: list[str] = []

    head = "\n".join(lines[:10])
    for key in ("**知识点**", "**本章回答**", "**示例目录**", "**读完应当能回答**"):
        if key not in head:
            issues.append(f"  章首缺少 {key}")

    m = re.search(r"^## 这一章建立的 (\d+) 件事", text, re.M)
    if not m:
        issues.append("  缺少「## 这一章建立的 N 件事」")
    else:
        declared = int(m.group(1))
        section = text[m.end():]
        section = re.split(r"^## ", section, maxsplit=1, flags=re.M)[0]
        items = re.findall(r"^\d+\. ", section, re.M)
        if declared != len(items):
            issues.append(f"  声称 {declared} 件事，实际 {len(items)} 条")

    if "## 下一章" not in text:
        issues.append("  缺少「## 下一章」")

    n = chinese_chars(text)
    if n < MIN_CHARS:
        issues.append(f"  中文字符 {n}，低于 {MIN_CHARS}")

    issues.extend(check_table_pipes(lines))

    for title in re.findall(r"^#{2,3} (.+)$", text, re.M):
        if len(re.findall(r"[\u4e00-\u9fff]", title)) > 12:
            issues.append(f"  标题超过 12 字：{title}")

    for num in re.findall(r"第 (\d{1,2}) 章", text):
        if not 0 <= int(num) <= 59:
            issues.append(f"  章号越界：第 {num} 章")

    if text.count("```") % 2:
        issues.append("  代码块不成对（``` 数为奇数）")

    return issues


def main() -> int:
    args = sys.argv[1:]
    if args == ["--all"]:
        files = sorted(
            p for p in ROOT.glob("*.md")
            if re.match(r"^\d{2}-", p.name) and not p.name.startswith("99")
        )
    elif args:
        files = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
    else:
        print(__doc__)
        return 2

    failed = 0
    for f in files:
        issues = check_file(f)
        status = "OK " if not issues else "FAIL"
        print(f"[{status}] {f.name}  中文字符={chinese_chars(f.read_text(encoding='utf-8'))}")
        for issue in issues:
            print(issue)
        failed += bool(issues)

    print(f"\n{len(files) - failed}/{len(files)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
