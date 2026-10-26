"""交接文件一致性检查。

运行：
    python tools/check_handoff.py

检查项：
    1. .github/copilot-instructions.md 与 AGENTS.md 内容相同
    2. docs/PROMPT.md 引用的文件与章节都真实存在
    3. docs 下被入口文件提及的文件都存在

这几项一旦失效，新会话会按错误的信息工作，且不容易被发现，
因此单独成脚本，与风格、引用、结构三项检查分开。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENTRY_FILES = [ROOT / ".github" / "copilot-instructions.md", ROOT / "AGENTS.md"]


def check_entry_files_identical(problems: list[str]) -> None:
    texts = []
    for p in ENTRY_FILES:
        if not p.exists():
            problems.append(f"入口文件不存在：{p.relative_to(ROOT)}")
            return
        texts.append(p.read_text(encoding="utf-8"))

    if texts[0] != texts[1]:
        rel = [str(p.relative_to(ROOT)) for p in ENTRY_FILES]
        problems.append(f"两份入口文件内容不一致：{rel[0]} 与 {rel[1]}，改一份必须同步另一份")


def check_referenced_paths(text: str, source: str, problems: list[str]) -> None:
    """检查文中用反引号标出的仓库内路径是否存在。

    只检查以 docs/ tools/ code/ tests/ 开头的显式路径。
    形如 CONTRACT.md 的裸文件名、含 XX 或 * 的占位符不检查。
    """
    pattern = r"`((?:docs|tools|code|tests)/[^`\s]+?)`"
    # 计划中尚未创建的目录，允许被引用
    PLANNED = {"code/finetune", "code/serving", "code/framework", "code/harness", "code/eval"}
    for m in re.finditer(pattern, text):
        rel = m.group(1).rstrip("/")
        if any(tok in rel for tok in ("XX", "NN", "*", "<", ">")):
            continue
        if rel in PLANNED:
            continue
        if not (ROOT / rel).exists():
            problems.append(f"{source} 引用了不存在的路径：{rel}")


def check_outline_sections(text: str, source: str, problems: list[str]) -> None:
    """检查形如 `OUTLINE.md` 5.8.1 的小节号在 OUTLINE 中真实存在。"""
    outline = (ROOT / "OUTLINE.md").read_text(encoding="utf-8")
    for m in re.finditer(r"5\.\d+(?:\.\d+)?", text):
        sec = m.group()
        # 只检查 5.x 形式且出现在「读 OUTLINE」相关语境的
        if f"### {sec} " in outline or f"### {sec}\n" in outline:
            continue
        # 5.1-5.6 是早期小节，标题可能不含编号，允许
        if sec in {"5.1", "5.2", "5.3", "5.4", "5.5", "5.6"}:
            continue
        problems.append(f"{source} 引用了 OUTLINE 中不存在的小节：{sec}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    problems: list[str] = []

    check_entry_files_identical(problems)

    prompt = ROOT / "docs" / "PROMPT.md"
    if prompt.exists():
        t = prompt.read_text(encoding="utf-8")
        check_referenced_paths(t, "docs/PROMPT.md", problems)
        check_outline_sections(t, "docs/PROMPT.md", problems)

    for p in ENTRY_FILES:
        if p.exists():
            check_referenced_paths(p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)), problems)

    if problems:
        for x in problems:
            print(f"  - {x}")
        print(f"\n共 {len(problems)} 个问题。")
        return 1

    print("交接文件一致，引用均有效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
