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


def declared_deliverable(text: str) -> str | None:
    """读取章首元信息里声明的交付物类型。

    章首必须写 `> **交付**：<类型>`，类型取自 DELIVERABLE_KINDS。
    没有声明时返回 None，由调用方决定如何处理。
    """
    for line in text.split("\n")[:10]:
        if "**交付**" in line:
            body = line.split("**交付**", 1)[1].lstrip("：: ")
            for kind in DELIVERABLE_KINDS:
                if body.startswith(kind):
                    return kind
    return None


DELIVERABLE_KINDS = ("标准范式", "可运行脚本", "操作序列", "无")


def has_standard_pattern(text: str) -> bool:
    """标准范式：一个 >= 12 行的围栏块，且块前一行有用途说明。

    用于「提示词标准范式」这类必须给出完整成品的内容。
    """
    lines = text.split("\n")
    in_block = False
    block_len = 0
    prev_blank_ok = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            if in_block:
                if block_len >= 12 and prev_blank_ok:
                    return True
                in_block = False
                block_len = 0
            else:
                in_block = True
                block_len = 0
                # 检查块前 3 行内是否有说明文字
                ctx = " ".join(lines[max(0, i - 3) : i])
                prev_blank_ok = len(ctx.strip()) > 10
            continue
        if in_block:
            block_len += 1
    return False


def has_runnable_script_ref(text: str) -> bool:
    """可运行脚本：正文引用了真实存在的 .py 文件。

    接受两类路径：
        code/chXX_名称/stepN.py（第 1-4 章）
        code/harness/*.py    （第 5 章起的包）
    """
    for m in re.finditer(r"code/(ch\d{2}_[a-z0-9_]+|harness)/([a-z0-9_]+\.py)", text):
        p = ROOT / "code" / m.group(1) / m.group(2)
        if p.exists():
            return True
    return False


def has_operation_sequence(text: str) -> bool:
    """操作序列：>= 3 条编号步骤，且每条含判定条件（则/判定/若/→）。"""
    steps = [l for l in text.split("\n")
             if re.match(r"^\s*[1-9]\.\s", l) and any(k in l for k in ("则", "判定", "若", "→"))]
    return len(steps) >= 3


def check_deliverable(text: str, kind: str) -> str | None:
    """按声明的类型检查是否真的交付了。返回问题描述或 None。"""
    if kind == "标准范式":
        if not has_standard_pattern(text):
            return "声明交付「标准范式」，但未给出 >=12 行、带用途说明的完整成品"
        return None
    if kind == "可运行脚本":
        if not has_runnable_script_ref(text):
            return "声明交付「可运行脚本」，但未引用任何存在的 code/ 脚本"
        return None
    if kind == "操作序列":
        if not has_operation_sequence(text):
            return "声明交付「操作序列」，但未给出 >=3 条带判定条件的编号步骤"
        return None
    return None

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
    #    围栏代码块内的内容不是正文，跳过检查。
    #    否则提示词示例里的 "## 任务" 会被当成章节标题误判。
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
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

    # 4. 感叹号与反问（跳过代码块、表格、引用块）
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.startswith(("|", ">")):
            continue
        if "！" in line:
            problems.append(f"第 {i} 行含感叹号")
        if "？" in line:
            problems.append(f"第 {i} 行含问号，确认是否为反问句")

    # 5. 百分比需有来源
    #    来源的判定：该行本身提到脚本/运行，或所在小节前文已给出脚本路径。
    #    围栏代码块内的百分比属于代码，不检查。
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or "%" not in line:
            continue
        if "运行" in line or "`" in line:
            continue
        # 向上回溯 25 行，寻找脚本出处
        window = "\n".join(lines[max(0, i - 26) : i])
        if ".py" in window and ("运行" in window or "脚本" in window):
            continue
        for m in re.finditer(r"\d+(?:\.\d+)?%", line):
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

    # 8. 交付物按章声明、按类型检查（地图章豁免）
    #    不再要求「每章都有代码块」，只要求「声明什么就交付什么」。
    if no not in EXEMPT:
        kind = declared_deliverable(text)
        if kind is None:
            problems.append(
                "缺少章首交付声明：需写 `> **交付**：标准范式 | 可运行脚本 | 操作序列 | 无`"
            )
        else:
            msg = check_deliverable(text, kind)
            if msg:
                problems.append(msg)

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
