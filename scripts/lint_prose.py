#!/usr/bin/env python3
"""散文体检：把《方案 v12》第二节的口径做成机检。

用法：
    python scripts/lint_prose.py --all
    python scripts/lint_prose.py 01-一次调用的四个字段.md

指标分两层：
    章级（check_chapters 口径，含标题与章末）—— 决定阅读时长，目标 6000–6800；
    散文级（去掉代码、表格、标题、章首引用块）—— 决定句法与节奏。

任何一项越界都会列在末尾。阈值定义见 docs/REFACTOR-v12-精简.md 第二节。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (键, 中文名, 下限, 上限)
LIMITS = [
    ("chapter_zh", "章汉字数", 0, 99999),      # 仅供参考：含不可改的章首与章末
    ("prose_zh", "散文汉字", 4800, 6250),
    # 代码块/输出块前的引导句本身就是一个短段，全书约 20 处，会拉低均值；
    # 真正要防的是"连续多段一句话"，由 short_run 单独判定。
    ("avg_para", "平均段长", 80, 140),
    ("bold_ratio", "粗体占比", 0.0, 0.035),
    ("dash", "破折号", 0, 8),
    ("not_but", "不是…而是", 0, 2),
    ("paren", "括号补充", 0, 10),
    ("you", "第二人称你", 0, 0),
    ("meta", "元话语", 0, 4),
    ("emotion", "情绪评价词", 0, 0),
]

META_PATTERNS = [
    r"这句话(决定|说明|值得)",
    r"这一(条|点)(单独|也|还)?值得",
    r"到(这里|这一步)可以",
    r"先说清",
    r"值得(单独)?(说|看一眼|一提)",
    r"(本节|本章|下面|后面|前面|上文|下文)(会|要|讲|的|再)",
    r"这(正)?是(为什么|本书|这一章)",
    r"(可以|需要)单独(说|看一眼)",
]
EMOTION_WORDS = [
    "致命", "灾难", "很贵", "很便宜", "极贵", "烧钱", "坑", "踩坑", "翻车",
    "可怕", "惊人", "糟糕", "硬伤", "武器", "毒打", "碾压", "暴击", "血亏",
]
ANTHRO_WORDS = ["兜住", "接住", "扛住", "撑住"]


def zh(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def chapter_zh(text: str) -> int:
    """与 scripts/check_chapters.py 同一口径。"""
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    body = re.sub(r"^\|.*$", "", body, flags=re.M)
    return zh(body)


def prose_only(text: str) -> str:
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    body = re.sub(r"^\|.*$", "", body, flags=re.M)
    body = re.sub(r"^#{1,6} .*$", "", body, flags=re.M)
    body = re.sub(r"^>.*$", "", body, flags=re.M)
    body = re.sub(r"^---+$", "", body, flags=re.M)
    return body


def paragraphs(body: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", body):
        b = block.strip()
        if not b:
            continue
        if re.match(r"^(?:[-*+]|\d+\.)\s", b):      # 列表项
            continue
        if b.startswith("[") and "](" in b:          # 目录链接
            continue
        out.append(b)
    return out


def measure(text: str) -> dict:
    body = prose_only(text)
    paras = paragraphs(body)
    body_lens = [(zh(p), p.rstrip().endswith("：")) for p in paras]
    lens = [n for n, _ in body_lens if n]
    para_lens = [n for n, lead in body_lens if n and not lead]
    total = sum(lens) or 1
    bold_zh = sum(zh(m) for m in re.findall(r"\*\*(.+?)\*\*", body, flags=re.S))
    run = best = 0
    for n in lens:
        run = run + 1 if n <= 20 else 0
        best = max(best, run)
    return {
        "chapter_zh": chapter_zh(text),
        "prose_zh": total,
        "paras": len(lens),
        "avg_para": round(sum(para_lens) / len(para_lens), 1) if para_lens else 0,
        "short_run": best,
        "bold_ratio": round(bold_zh / total, 3),
        "dash": body.count("——"),
        "not_but": len(re.findall(r"不是[^。\n]{1,20}，?而是", body)),
        "paren": len(re.findall(r"（[^）]{6,}）", body)),
        "you": body.count("你"),
        "meta": sum(len(re.findall(p, body)) for p in META_PATTERNS),
        "emotion": sum(body.count(w) for w in EMOTION_WORDS),
        "anthro": sum(body.count(w) for w in ANTHRO_WORDS),
    }


def report(path: Path) -> list[str]:
    m = measure(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    print(f"\n{path.name}")
    print(f"  {'指标':<12}{'实测':>8}   {'目标':<12}")
    for key, label, lo, hi in LIMITS:
        val = m[key]
        ok = lo <= val <= hi
        rng = f"{lo}–{hi}"
        print(f"  {label:<12}{val:>8}   {rng:<12}{'' if ok else '  <<<'}")
        if not ok:
            problems.append(f"  {label} = {val}（目标 {rng}）")
    print(f"  {'段落数':<12}{m['paras']:>8}")
    if m["short_run"] > 2:
        problems.append(f"  连续 {m['short_run']} 段 ≤20 字（目标 ≤2）")
    if m["anthro"]:
        problems.append(f"  拟人动词 {m['anthro']} 处（目标 0）")
    return problems


def main() -> int:
    args = sys.argv[1:]
    if args == ["--all"]:
        files = sorted(p for p in ROOT.glob("*.md") if re.match(r"^\d{2}-", p.name))
    elif args:
        files = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
    else:
        print(__doc__)
        return 2

    bad = 0
    for f in files:
        problems = report(f)
        if problems:
            bad += 1
            for p in problems:
                print(p)
    print(f"\n{len(files) - bad}/{len(files)} 章达标")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
