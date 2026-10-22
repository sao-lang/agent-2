"""检查所有 Markdown 相对链接是否指向真实存在的文件（重编号后必跑）。

用法（项目根目录）：
    python tools/check_links.py

只检查同目录下的相对链接（`](xxx.md)`），跳过 http(s)、锚点、mailto。
退出码非 0 表示有坏链。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    bad: list[tuple[Path, str]] = []
    total = 0
    for md in sorted(ROOT.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        in_code = False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for m in LINK.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                total += 1
                if not (md.parent / target).exists():
                    bad.append((md, target))

    for md, target in bad:
        print(f"  ❌ {md.name} -> {target}")
    print(f"\n检查 {total} 个相对链接，坏链 {len(bad)} 个")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
