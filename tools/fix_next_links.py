"""修正所有章节末尾的「下一页：」链接（重编号后的一次性修复）。

文件名已经在 `git mv` 里改过了，但 `下一页：` 后面的链接目标还是旧文件名。
这个脚本按"新编号 → 新文件名"的映射，把链接目标换成真实存在的文件，并顺便
把链接文字里的章号一起对齐。

用法（项目根目录）：
    python tools/fix_next_links.py            # 预览
    python tools/fix_next_links.py --write    # 写入
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NEXT_LINE = re.compile(r"^下一页：\[([^\]]+)\]\(([^)]+)\)\s*$")


def build_index() -> dict[str, Path]:
    """{章号两位数: 文件} —— 只收正文章节。"""
    out: dict[str, Path] = {}
    for p in ROOT.glob("[0-9][0-9]-*.md"):
        out[p.name[:2]] = p
    return out


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    write = "--write" in argv
    index = build_index()

    fixed = 0
    missing = 0
    for p in sorted(ROOT.glob("[0-9][0-9]-*.md")):
        lines = p.read_text(encoding="utf-8").split("\n")
        changed = False
        for i, line in enumerate(lines):
            m = NEXT_LINE.match(line)
            if not m:
                continue
            text = m.group(1)
            # 目标章号 = 当前章号 + 1（`下一页` 的定义）
            cur = int(p.name[:2])
            nxt = f"{cur + 1:02d}"
            if nxt not in index:
                missing += 1
                print(f"  ⚠️ {p.name}: 第 {nxt} 章还没写，先跳过")
                continue
            real = index[nxt].name
            new_text = re.sub(r"第 \d+ 章", f"第 {cur + 1} 章", text)
            new_line = f"下一页：[{new_text}]({real})"
            if new_line != line:
                lines[i] = new_line
                changed = True
                fixed += 1
                print(f"  {p.name}: {line.strip()}  →  {new_line}")

        if changed and write:
            p.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'已写入' if write else '预览'}：修正 {fixed} 处，跳过 {missing} 处（目标章未写）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
