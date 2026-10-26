"""测试基础设施自检。

本文件只验证 tests/ 与 pytest 配置可用，不含业务逻辑。
第 5 章起，每个组件在 tests/test_<组件>.py 中单独测试。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_harness_package_path_exists() -> None:
    """code/harness 目录存在且被 git 追踪（否则克隆后测试必失败）。"""
    pkg = ROOT / "code" / "harness"
    assert pkg.is_dir(), "code/harness 目录不存在"
    assert (pkg / ".gitkeep").exists(), "code/harness 缺少 .gitkeep，空目录不会被 git 追踪"


def test_code_root_on_path() -> None:
    """pytest.ini 的 pythonpath 已把 code/ 放进 sys.path。"""
    code_root = str(ROOT / "code")
    assert any(str(Path(p).resolve()) == str(Path(code_root).resolve()) for p in sys.path if p), (
        f"code/ 不在 sys.path 上：{sys.path}"
    )


def test_chapter_files_follow_naming() -> None:
    """章节文件名为 NN-标题.md，NN 为两位数字。"""
    for p in ROOT.glob("[0-9][0-9]-*.md"):
        assert re.match(r"^\d{2}-.+\.md$", p.name), f"命名不符：{p.name}"


def test_entry_files_in_sync() -> None:
    """AGENTS.md 与 .github/copilot-instructions.md 必须完全一致。"""
    a = ROOT / "AGENTS.md"
    b = ROOT / ".github" / "copilot-instructions.md"
    assert a.exists() and b.exists(), "入口文件缺失"
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8"), (
        "两份入口文件内容不一致，运行 python tools/check_handoff.py 查看差异"
    )


def test_checkers_pass() -> None:
    """四个结构检查脚本全部通过。"""
    for name in ("check_style.py", "check_refs.py", "check_chapter.py", "check_handoff.py"):
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / name)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, f"{name} 未通过：\n{r.stdout}{r.stderr}"
