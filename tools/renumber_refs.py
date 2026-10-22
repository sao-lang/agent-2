"""把全书"第 N 章"的引用从**原始编号**改成**新编号**（一次性迁移）。

背景：《整合映射表.md》决定用方案 B（严格重编号）。文件已经 `git mv` 过了，
正文里还残留旧编号，读者按图索骥会走错。

用法（项目根目录，**只跑一次**）：
    python tools/renumber_refs.py            # 预览
    python tools/renumber_refs.py --write    # 写入

设计要点（很重要，改错一次很难回滚）：
  · 编号一律按**原始编号**映射，不"读当前文本再映射" —— 否则会二次映射
  · 标题 `# 第 N 章` 按**文件名前缀**重写（文件名已经是新编号）
  · 代码块与 Markdown 链接目标 `](NN-...md)` 一律不动
  · 附录等没有章号的文件只改引用，不改标题
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 原始编号 → 新编号（只列发生变化的）
ORIGINAL = {
    10: 11, 11: 12, 12: 13, 13: 14, 14: 15, 15: 16, 16: 17, 17: 18, 18: 19,
    19: 20, 20: 21, 21: 22, 22: 23, 23: 24, 24: 25, 25: 26, 26: 37, 27: 38, 28: 42,
}

CH_REF = re.compile(r"第 ([\d、\-–—至,，\s]+) 章")
LINK_TARGET = re.compile(r"\]\([^)]*\)")


def remap(n: int) -> int:
    return ORIGINAL.get(n, n)


def fix_segment(seg: str) -> str:
    """只处理一段非代码文本；链接目标先摘出去，改完再放回。"""
    stash: list[str] = []

    def keep(m: re.Match[str]) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    seg = LINK_TARGET.sub(keep, seg)

    def repl(m: re.Match[str]) -> str:
        pieces = re.split(r"(\d+)", m.group(1))
        out = [str(remap(int(p))) if p.isdigit() else p for p in pieces]
        return "第 " + "".join(out) + " 章"

    seg = CH_REF.sub(repl, seg)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], seg)


def transform(path: Path) -> tuple[str, str]:
    original = path.read_text(encoding="utf-8")
    text = original

    head = path.name[:2]
    if head.isdigit():
        text = re.sub(r"^(# 第 )\d+( 章)", rf"\g<1>{int(head)}\g<2>", text, count=1, flags=re.MULTILINE)

    parts = text.split("```")
    for i in range(0, len(parts), 2):
        parts[i] = fix_segment(parts[i])
    return original, "```".join(parts)


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    write = "--write" in argv

    total = 0
    for p in sorted(ROOT.glob("*.md")):
        original, new = transform(p)
        if new == original:
            continue
        if write:
            p.write_text(new, encoding="utf-8")
        old_lines = set(original.split("\n"))
        changed = [ln.strip()[:110] for ln in new.split("\n") if ln.strip() and ln not in old_lines]
        total += len(changed)
        print(f"{p.name}: {len(changed)} 行")
        for c in changed[:3]:
            print(f"    {c}")

    print(f"\n{'已写入' if write else '预览'}：{total} 行改动")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
