#!/usr/bin/env python3
"""把一章切成「散文 / 受保护块」，输出改写视图与段表。

用法：
    python scripts/trim_split.py 01-一次调用的四个字段.md

产物（放在 .trim/ 下）：
    01.seg.json   段表，记录每个受保护块的原文与 sha256
    01.view.md    改写视图：受保护块变成 ⟦P0001⟧，只留散文可改

改写流程：在 view.md 上改散文 → 存成 01.new.md → trim_apply.py 回填 → trim_verify.py 校验。
受保护块物理上不经过改写者，因此代码、输出、表格、标题不会被改坏。

受保护块包括：围栏代码块（含内部空行）、各级标题、表格、章首引用块、
章内目录、`---` 分隔线、以及从「## 这一章建立的」到文件末尾的全部内容。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".trim"

TOC_LINE = re.compile(r"^\[[^\]]+\]\(#[^)]*\)\\?$")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_tail(line: str) -> bool:
    return line.startswith("## 这一章建立的")


def split_lines(text: str) -> list[dict]:
    lines = text.replace("\r\n", "\n").split("\n")
    segs: list[dict] = []
    i, n = 0, len(lines)

    def push(kind: str, chunk: list[str]) -> None:
        body = "\n".join(chunk).strip("\n")
        if body.strip():
            segs.append({"kind": kind, "text": body, "sha": sha(body)})

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if is_tail(line):
            push("P", lines[i:])
            break

        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            j = i + 1
            while j < n and not lines[j].strip().startswith(fence):
                j += 1
            push("P", lines[i:min(j + 1, n)])
            i = j + 1
            continue

        if stripped.startswith("#"):
            push("P", [line])
            i += 1
            continue

        if stripped.startswith("|"):
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            push("P", lines[i:j])
            i = j
            continue

        if stripped.startswith(">"):
            j = i
            while j < n and lines[j].strip().startswith(">"):
                j += 1
            push("P", lines[i:j])
            i = j
            continue

        if TOC_LINE.match(stripped):
            j = i
            while j < n and TOC_LINE.match(lines[j].strip()):
                j += 1
            push("P", lines[i:j])
            i = j
            continue

        if stripped in ("---", "***"):
            push("P", [line])
            i += 1
            continue

        # 散文：吃到空行或下一个受保护结构的开头
        j = i
        chunk: list[str] = []
        while j < n:
            s = lines[j].strip()
            if not s:
                break
            if chunk and (s.startswith(("#", "|", ">", "```", "~~~"))
                          or TOC_LINE.match(s) or is_tail(lines[j])):
                break
            chunk.append(lines[j])
            j += 1
        push("S", chunk)
        i = j
        while i < n and not lines[i].strip():
            i += 1  # 跳过空行

    return segs


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    OUT.mkdir(exist_ok=True)

    for a in args:
        path = Path(a) if Path(a).is_absolute() else ROOT / a
        segs = split_lines(path.read_text(encoding="utf-8"))
        stem = re.match(r"^\d{2}", path.name).group(0)
        (OUT / f"{stem}.seg.json").write_text(
            json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")

        view = []
        for idx, s in enumerate(segs, 1):
            view.append(f"⟦P{idx:04d}⟧" if s["kind"] == "P" else s["text"])
        (OUT / f"{stem}.view.md").write_text("\n\n".join(view) + "\n", encoding="utf-8")

        n_p = sum(1 for s in segs if s["kind"] == "P")
        zh = sum(len(re.findall(r"[\u4e00-\u9fff]", s["text"])) for s in segs if s["kind"] == "S")
        print(f"{path.name}: 受保护块 {n_p} 个，可改散文 {len(segs) - n_p} 段，散文汉字 {zh}")
        print(f"  段表 .trim/{stem}.seg.json　视图 .trim/{stem}.view.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
