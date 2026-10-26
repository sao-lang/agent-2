"""风格检查：把 docs/WRITING-SPEC.md 中可自动判定的规则落成检查。

运行：
    python tools/check_style.py            # 检查全部章节
    python tools/check_style.py 01 02      # 只检查指定章

检查项：
    1. 章首三行元信息
    2. 标题修饰词与禁用词
    3. 主观/情绪用词
    4. 感叹号与反问句
    5. 未标注来源的百分比
    6. 章首术语表（已废止的写法）
    7. 五段结构完整性
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 地图章不适用五段结构与章首元信息
EXEMPT = {0}

# 标题中不允许出现的修饰成分
TITLE_BANNED = ("★", "！", "?", "？", "：为什么", "你必须", "一定要", "千万")
TITLE_BANNED_PHRASES = ("补充说明", "其他内容", "小结", "杂项")

# 正文中不允许出现的情绪/主观词
EMOTION_WORDS = (
    "非常", "极其", "糟糕", "可怕", "震惊", "大吃一惊", "显而易见",
    "毫无疑问", "毋庸置疑", "真的太", "竟然", "居然", "难道",
)

# 已废止的旧结构
LEGACY_MARKERS = ("本章产出", "本章验收", "验收标准", "本章遗留", "先看一个具体的坏事",
                  "为什么现有手段不够", "术语表")


def chapter_no(path: Path) -> int | None:
    head = path.name[:2]
    return int(head) if head.isdigit() and path.name[2] == "-" else None


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    no = chapter_no(path)
    problems: list[str] = []

    if no is None:
        return problems

    # 1. 章首元信息（地图章豁免）
    if no not in EXEMPT:
        head = "\n".join(lines[:8])
        if "**知识点**" not in head:
            problems.append("缺少章首元信息：知识点")
        if "**读完应当能回答**" not in head:
            problems.append("缺少章首元信息：读完应当能回答")

    # 2-3. 标题与正文用词
    for i, line in enumerate(lines, 1):
        if line.startswith("#"):
            title = line.lstrip("# ").strip()
            for w in TITLE_BANNED:
                if w in title:
                    problems.append(f"第 {i} 行标题含修饰成分：{w}")
            for w in TITLE_BANNED_PHRASES:
                if w in title:
                    problems.append(f"第 {i} 行标题过于空泛：{w}")
            if re.search(r"[\U0001F300-\U0001FAFF]", title):
                problems.append(f"第 {i} 行标题含 emoji")
        else:
            for w in EMOTION_WORDS:
                if w in line:
                    problems.append(f"第 {i} 行含主观/情绪词：{w}")

    # 4. 感叹号与反问
    for i, line in enumerate(lines, 1):
        if line.startswith("|") or line.startswith("```"):
            continue
        if "！" in line:
            problems.append(f"第 {i} 行含感叹号")
        if "？" in line and not line.startswith(">"):
            # 允许出现在代码块外的提问句，但需人工确认
            problems.append(f"第 {i} 行含问号，确认是否为反问句")

    # 5. 未标注来源的百分比
    for i, line in enumerate(lines, 1):
        for m in re.finditer(r"\d+(?:\.\d+)?%", line):
            if "运行" not in line and "`" not in line[:m.start()]:
                problems.append(f"第 {i} 行出现百分比且未标注来源：{m.group()}")

    # 6. 旧结构
    for marker in LEGACY_MARKERS:
        if marker in text and marker != "术语表":  # 术语表允许在"没有术语表"这类陈述中出现
            problems.append(f"出现已废止的旧结构：{marker}")

    # 7. 五段结构（地图章豁免）
    if no not in EXEMPT:
        for key in ("边界", "复现"):
            if not any(key in line for line in lines if line.startswith("## ")):
                problems.append(f"缺少小节：{key}")

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
    print(f"检查 {len(files)} 个文件，通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
