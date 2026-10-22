"""第 0 步产出：章节质量检查脚本。

运行（项目根目录）：
    python tools/check_chapters.py            # 检查全部章节
    python tools/check_chapters.py --min 8000 # 覆盖最低字符数（重构期用）
    python tools/check_chapters.py 03 04      # 只检查指定编号

它检查《下一轮任务提示词》第 4.3 节的质量门槛里可以自动判定的部分：

    1. 13 节模板的标题是否齐全
    2. 是否有 N.0 术语表
    3. 是否有 💥 失败实验
    4. 字符数 / 行数是否达标
    5. N.10 是否标注「可跳过」
    6. 正文里是否混进了框架名（应放到 N.10 或独立框架章）

不做的事：不判断内容质量，也不代替人读一遍。脚本只能拦住"漏节"，拦不住"写得不好"。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 准备类文档不参与模板检查
EXEMPT = {"00-如何使用本书.md", "README.md", "整合映射表.md", "下一轮任务提示词.md", "项目说明.md"}

MIN_CHARS = 12000
MIN_LINES = 500

TEMPLATE_SECTIONS = [
    ("N.0", r"^##\s+\d+\.0\s"),
    ("N.1", r"^##\s+\d+\.1\s"),
    ("N.2", r"^##\s+\d+\.2\s"),
    ("N.3", r"^##\s+\d+\.3\s"),
    ("N.4", r"^##\s+\d+\.4\s"),
    ("N.5", r"^##\s+\d+\.5\s"),
    ("N.6", r"^##\s+\d+\.6\s"),
    ("N.7", r"^##\s+\d+\.7\s"),
    ("N.8", r"^##\s+\d+\.8\s"),
    ("N.9", r"^##\s+\d+\.9\s"),
    ("N.10", r"^##\s+\d+\.10\s"),
    ("N.11", r"^##\s+\d+\.11\s"),
    ("N.12", r"^##\s+\d+\.12\s"),
]

# 这些名字出现在 N.10 之前的正文里，说明"外部标准混进了正文"
FRAMEWORK_WORDS = ("langchain", "langgraph", "llamaindex", "ragas", "langfuse", "langsmith", "opentelemetry")

# 独立框架章本来就在讲框架，不检查第 6 项
FRAMEWORK_CHAPTERS = {27, 28, 29, 30, 31, 32, 33, 34, 35, 36}


@dataclass
class Report:
    path: Path
    chapter_no: int | None
    chars: int
    lines: int
    missing_sections: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_sections and not self.problems


def chapter_number(name: str) -> int | None:
    m = re.match(r"^(\d{2})-", name)
    return int(m.group(1)) if m else None


def section_body(text: str, no: int, sec: str, next_sec: str) -> str:
    """取出 `N.sec` 到 `N.next_sec` 之间的正文。"""
    start = re.search(rf"^##\s+{no}\.{sec}\s.*$", text, re.MULTILINE)
    if not start:
        return ""
    end = re.search(rf"^##\s+{no}\.{next_sec}\s", text[start.end() :], re.MULTILINE)
    return text[start.end() : start.end() + end.start()] if end else text[start.end() :]


def check_optional_section(text: str, no: int) -> list[str]:
    body = section_body(text, no, "10", "11")
    if body and "跳过" not in body:
        return ["N.10 必须标注「可跳过」"]
    return []


def check_body_frameworks(text: str, no: int) -> list[str]:
    """只统计"整段在讲框架"的数量：一行里出现 3 次以上才算跑题。

    正文里一句话提到"Langfuse 界面底层也是这几个字段"是合法的类比，
    不该被判为"把外部标准混进正文"。
    """
    if no in FRAMEWORK_CHAPTERS:
        return []
    start = re.search(rf"^##\s+{no}\.1\s", text, re.MULTILINE)
    end = re.search(rf"^##\s+{no}\.10\s", text, re.MULTILINE)
    if not start or not end:
        return []
    body = text[start.start() : end.start()].lower()
    hits = sorted({w for w in FRAMEWORK_WORDS if body.count(w) >= 3})
    return [f"正文 N.1–N.9 多次出现框架名：{', '.join(hits)}（应移到 N.10）"] if hits else []


def check_file(path: Path, min_chars: int) -> Report:
    text = path.read_text(encoding="utf-8")
    no = chapter_number(path.name)
    rep = Report(path=path, chapter_no=no, chars=len(text), lines=text.count("\n") + 1)

    if no is None:  # 附录
        return rep

    rep.missing_sections = [label for label, pat in TEMPLATE_SECTIONS if not re.search(pat, text, re.MULTILINE)]

    if not re.search(r"^\|\s*术语\s*\|", text, re.MULTILINE):
        rep.problems.append("缺少 N.0 术语表表格（表头需含「术语」列）")
    if "💥" not in text:
        rep.problems.append("缺少 💥 失败实验")
    if rep.chars < min_chars:
        rep.problems.append(f"字符数 {rep.chars:,} < {min_chars:,}")
    if rep.lines < MIN_LINES:
        rep.problems.append(f"行数 {rep.lines} < {MIN_LINES}")

    rep.problems.extend(check_optional_section(text, no))
    rep.problems.extend(check_body_frameworks(text, no))
    return rep


def main(argv: list[str]) -> int:
    # Windows 默认 GBK 控制台会因为 ✅ / 💥 直接崩，统一改成 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    min_chars = MIN_CHARS
    only: set[str] = set()
    it = iter(argv[1:])
    for a in it:
        if a == "--min":
            min_chars = int(next(it))
        else:
            only.add(a.zfill(2))

    files = sorted(p for p in ROOT.glob("[0-9][0-9]-*.md") if p.name not in EXEMPT)
    if only:
        files = [p for p in files if p.name[:2] in only]

    reports = [check_file(p, min_chars) for p in files]

    print(f"{'文件':<40}{'字符':>9}{'行':>6}  状态")
    print("-" * 74)
    for r in reports:
        print(f"{r.path.name:<40}{r.chars:>9,}{r.lines:>6}  {'✅' if r.ok else '❌'}")

    bad = [r for r in reports if not r.ok]
    if bad:
        print("\n不合格明细：")
        for r in bad:
            if r.missing_sections:
                print(f"  {r.path.name}  缺节：{', '.join(r.missing_sections)}")
            for p in r.problems:
                print(f"  {r.path.name}  {p}")
        print(f"\n共 {len(bad)}/{len(reports)} 章未达标。")
        return 1

    print(f"\n全部 {len(reports)} 章达标。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
