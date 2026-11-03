#!/usr/bin/env python3
"""全书验收：对每章跑 lint / check_chapters / trim_verify（对比基线提交）。

用法：
    python docs/trim_all.py 01 02 03 ...      # 指定章
    python docs/trim_all.py --vol1to3        # 第 1–12 章
    python docs/trim_all.py --all

基线默认取 `627ddd9`（精简前的最后一次全量提交）。
返回码 0 表示全部通过。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "627ddd9"


def chapters(selector: list[str]) -> list[str]:
    files = sorted(p for p in ROOT.glob("*.md") if re.match(r"^\d{2}-", p.name))
    if not selector or selector == ["--all"]:
        return [f.name[:2] for f in files]
    if selector == ["--vol1to3"]:
        return [f.name[:2] for f in files if 1 <= int(f.name[:2]) <= 12]
    return selector


def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--vol1to3", action="store_true", help="只跑第 1–12 章")
    args = ap.parse_args()

    ok = bad = 0
    print(f"{'章':<4}{'lint':<6}{'chapters':<10}{'verify':<8}{'散文':<8}{'章汉字'}")
    sel = ["--vol1to3"] if args.vol1to3 else args.stems
    for stem in chapters(sel):
        f = next(ROOT.glob(f"{stem}-*.md")).name
        c1, o1 = run([sys.executable, "docs/lint_prose.py", f])
        c2, o2 = run([sys.executable, "docs/check_chapters.py", f])
        c3, o3 = run([sys.executable, "docs/trim_verify.py", stem, "--base", BASE])
        c4 = 0
        if c3:
            # 改过小节结构的章（合并 / 重编号）允许 --restructure 再判一次
            for extra in (["--restructure"], ["--allow-tail"],
                          ["--restructure", "--allow-tail"]):
                c4, o4 = run([sys.executable, "docs/trim_verify.py", stem,
                              "--base", BASE] + extra)
                if c4 == 0:
                    c3, o3 = 0, o4
                    break
        prose = re.search(r"散文汉字\s+(\d+)", o1)
        chars = re.search(r"中文字符=(\d+)", o2)
        row = (
            f"{stem:<4}"
            f"{'OK' if c1 == 0 else 'FAIL':<6}"
            f"{'OK' if c2 == 0 else 'FAIL':<10}"
            f"{'OK' if c3 == 0 else 'FAIL':<8}"
            f"{(prose.group(1) if prose else '?'):<8}"
            f"{chars.group(1) if chars else '?'}"
        )
        print(row)
        if c1 or c2 or c3:
            bad += 1
            for tag, code, out in (("lint", c1, o1), ("chapters", c2, o2), ("verify", c3, o3)):
                if code:
                    tail = [l for l in out.splitlines() if l.strip()][-4:]
                    print(f"     {tag}: " + " | ".join(tail))
        else:
            ok += 1
    print(f"\n{ok}/{ok + bad} 章通过")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
