#!/usr/bin/env python3
"""把改写后的散文回填成完整章节（按「散文段」对齐，不手写序号）。

用法：
    python docs/trim_apply.py 01 .trim/01.new.md            # → .trim/01.final.md
    python docs/trim_apply.py 01 .trim/01.new.md -o out.md

约定：改写文件里**只有散文**，段与段之间用一行 ⟦GAP⟧ 分隔。散文段数必须等于
原文的散文段数（受保护块把原文切成的那些空隙），一段对一段。受保护块
（代码块、输出块、表格、标题、章首、章内目录、章末）按原顺序整组还原，
散文段内部可以自由合并、拆分、重写。

段数不符即失败，并指出是第几段对不上，不写文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".trim"
GAP = "⟦GAP⟧"


def rebuild(segs: list[dict], parts: list[str]) -> tuple[str, int, int]:
    out: list[str] = []
    buf_p: list[str] = []
    buf_s: list[str] = []
    pi = 0

    def flush_p() -> None:
        if buf_p:
            out.append("\n\n".join(buf_p))
            buf_p.clear()

    for s in segs:
        if s["kind"] == "P":
            if buf_s:
                flush_p()                      # 先吐出前面的受保护块
                if pi >= len(parts):
                    raise IndexError(f"散文段不够：第 {pi + 1} 段缺失")
                out.append(parts[pi])
                pi += 1
                buf_s.clear()
            buf_p.append(s["text"])
        else:
            buf_s.append(s["text"])
    if buf_s:
        flush_p()
        if pi >= len(parts):
            raise IndexError(f"散文段不够：第 {pi + 1} 段缺失")
        out.append(parts[pi])
        pi += 1
    flush_p()
    return "\n\n".join(x for x in out if x.strip()), pi, len(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem")
    ap.add_argument("new")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    seg_path = OUT / f"{args.stem}.seg.json"
    if not seg_path.exists():
        print(f"缺少段表 {seg_path}，先跑 trim_split.py", file=sys.stderr)
        return 2

    segs = json.loads(seg_path.read_text(encoding="utf-8"))
    raw = Path(args.new).read_text(encoding="utf-8")
    parts = [p.strip() for p in raw.split(GAP)]

    try:
        text, used, given = rebuild(segs, parts)
    except IndexError as e:
        print(f"散文段数量不符：原文需要更多段（{e}）", file=sys.stderr)
        return 1

    if used != given:
        print(f"散文段数量不符：原文 {used} 段，改写文件给了 {given} 段"
              f"（多了 {given - used} 段）", file=sys.stderr)
        return 1

    text = text.strip() + "\n"
    dest = Path(args.out) if args.out else OUT / f"{args.stem}.final.md"
    dest.write_text(text, encoding="utf-8")
    print(f"已回填 {used} 段散文 → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
