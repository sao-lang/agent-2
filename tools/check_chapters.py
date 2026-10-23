"""第 0 步产出：章节质量检查脚本。

运行（项目根目录）：
    python tools/check_chapters.py            # 检查全部章节
    python tools/check_chapters.py --min 8000 # 覆盖最低字符数（重构期用）
    python tools/check_chapters.py 03 04      # 只检查指定编号

它检查《下一轮任务提示词》第 57.3 节的质量门槛里可以自动判定的部分：

    1. 13 节模板的标题是否齐全
    2. 是否有 N.0 术语表
    3. 是否有失败实验标记
    4. 字符数 / 行数是否达标
    5. N.10 是否标注「可跳过」
    6. 正文里是否混进了框架名（应放到 N.10 或独立框架章）

不做的事：不判断内容质量，也不代替人读一遍。脚本只能拦住"漏节"，拦不住"写得不好"。

实现约定：全部按行扫描，不用正则。正则里的美元符号和前瞻断言会被 PowerShell 当作
自己的语法展开，导致匹配静默错位 —— 这类 bug 表现为"检查器说有错，人看明明没错"。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 准备类文档不参与模板检查
EXEMPT = {"00-如何使用本书.md", "README.md", "整合映射表.md", "下一轮任务提示词.md", "项目说明.md"}

MIN_CHARS = 12000
MIN_LINES = 500
FAIL_EXPERIMENT_MARK = "\U0001f4a5"  # 爆炸图标：失败实验的标记
TABLE_HEADER = "| 术语 |"
OPTIONAL_HINT = "跳过"

# 模板要求的 13 节：N.0 ~ N.12
TEMPLATE_SECTIONS = [str(i) for i in range(13)]

# 在正文（N.1~N.9）里出现 3 次以上，说明"外部标准混进了正文"
FRAMEWORK_WORDS = (
    "langchain",
    "langgraph",
    "llamaindex",
    "ragas",
    "langfuse",
    "langsmith",
    "opentelemetry",
)

# 独立框架章本来就在讲框架，不检查第 6 项
FRAMEWORK_CHAPTERS = {
    27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
    41,  # 系统集成与 Docker 交付：编排里必然出现具体服务名
    43, 44, 45, 46, 48, 49, 50, 51, 52, 53, 54,
    61,  # Agent 评测：必须点名具体框架的 interrupt/checkpointer 才能讲清
    62,  # 其他框架对比：整章就是横向对比，框架名是正文主体
}


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
    head = name[:2]
    return int(head) if head.isdigit() and name[2:3] == "-" else None


def section_of(line: str, no: int) -> str | None:
    """`## 14.10 ✅ 验收` → `10`。不是本章二级标题时返回 None。

    标题里编号后面可能是空格、也可能直接跟 emoji（`📦`），
    所以按"读出前缀后的连续数字"来取小节号，而不是按空格切。
    """
    prefix = "## " + str(no) + "."
    if not line.startswith(prefix):
        return None
    rest = line[len(prefix) :]
    digits = ""
    for ch in rest:
        if not ch.isdigit():
            break
        digits += ch
    if not digits:
        return None
    # `7.8.1` 这种三级编号不算独立小节
    if rest[len(digits) : len(digits) + 1] == ".":
        return None
    return digits


def outline(text: str, no: int) -> dict[str, list[str]]:
    """把本章的二级标题切开：{小节号: 正文行}。"""
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.split("\n"):
        sec = section_of(line, no)
        if sec is not None:
            current = sec
            result.setdefault(sec, [])
            continue
        if line.startswith("## " + str(no) + "."):
            # 三级编号（7.8.1）：正文继续挂在上一个小节下
            if current is not None:
                result[current].append(line)
            continue
        if current is not None:
            result[current].append(line)
    return result


def body_of(sections: dict[str, list[str]], sec: str) -> str:
    return "\n".join(sections.get(sec, []))


def check_optional_section(sections: dict[str, list[str]]) -> list[str]:
    """从 N.10 起，必须有一节明确写"可以先跳过"（N.10/N.11/...都算）。"""
    tail = [sec for sec in sections if sec.isdigit() and int(sec) >= 10]
    if not tail:
        return ["缺少标注「可跳过」的章节（N.10 起应有可选阅读）"]
    if not any(OPTIONAL_HINT in line for sec in tail for line in sections[sec]):
        return ["N.10 起必须有一节标注「可跳过」"]
    return []


def check_body_frameworks(sections: dict[str, list[str]], no: int) -> list[str]:
    """只统计"整段在讲框架"：某个名字在 N.1~N.9 出现 3 次以上才算跑题。

    正文里一句话提到"某个平台界面底层也是这几个字段"是合法的类比。
    """
    if no in FRAMEWORK_CHAPTERS:
        return []
    body = "\n".join(body_of(sections, str(i)) for i in range(1, 10)).lower()
    hits = sorted({w for w in FRAMEWORK_WORDS if body.count(w) >= 3})
    return [f"正文 N.1–N.9 多次出现框架名：{', '.join(hits)}（应移到 N.10）"] if hits else []


def check_file(path: Path, min_chars: int) -> Report:
    text = path.read_text(encoding="utf-8")
    no = chapter_number(path.name)
    rep = Report(path=path, chapter_no=no, chars=len(text), lines=text.count("\n") + 1)

    if no is None:  # 附录等
        return rep

    sections = outline(text, no)
    rep.missing_sections = [f"N.{s}" for s in TEMPLATE_SECTIONS if s not in sections]

    if TABLE_HEADER not in text:
        rep.problems.append("缺少 N.0 术语表表格（表头需含「术语」列）")
    if FAIL_EXPERIMENT_MARK not in text:
        rep.problems.append("缺少失败实验（爆炸图标标记）")
    if rep.chars < min_chars:
        rep.problems.append(f"字符数 {rep.chars:,} < {min_chars:,}")
    if rep.lines < MIN_LINES:
        rep.problems.append(f"行数 {rep.lines} < {MIN_LINES}")

    rep.problems.extend(check_optional_section(sections))
    rep.problems.extend(check_body_frameworks(sections, no))
    return rep


def main(argv: list[str]) -> int:
    # Windows 默认 GBK 控制台会因为 emoji 直接崩，统一改成 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="检查章节是否符合 13 节模板与质量门槛")
    parser.add_argument("numbers", nargs="*", help="只检查指定章号，如 03 04")
    parser.add_argument("--min", type=int, default=MIN_CHARS, help="最低字符数")
    args = parser.parse_args(argv[1:])

    only = {n.zfill(2) for n in args.numbers}
    files = sorted(p for p in ROOT.glob("[0-9][0-9]-*.md") if p.name not in EXEMPT)
    if only:
        files = [p for p in files if p.name[:2] in only]

    reports = [check_file(p, args.min) for p in files]

    print(f"{'文件':<40}{'字符':>9}{'行':>6}  状态")
    print("-" * 74)
    for r in reports:
        print(f"{r.path.name:<40}{r.chars:>9,}{r.lines:>6}  {'OK' if r.ok else 'FAIL'}")

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
