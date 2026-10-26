"""测试基础设施自检。

本文件只验证 tests/ 与 pytest 配置可用，不含业务逻辑。
第 5 章起，每个组件在 tests/test_<组件>.py 中单独测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_harness_package_path_exists() -> None:
    """code/harness 目录存在，且可加入 sys.path。"""
    pkg = ROOT / "code" / "harness"
    assert pkg.is_dir(), "code/harness 目录不存在"


def test_code_root_on_path() -> None:
    """pytest.ini 的 pythonpath 已把 code/ 放进 sys.path。"""
    code_root = str(ROOT / "code")
    assert any(str(Path(p).resolve()) == str(Path(code_root).resolve()) for p in sys.path if p), (
        f"code/ 不在 sys.path 上：{sys.path}"
    )


def test_chapter_files_follow_naming() -> None:
    """章节文件名为 NN-标题.md，NN 为两位数字。"""
    import re

    for p in ROOT.glob("[0-9][0-9]-*.md"):
        assert re.match(r"^\d{2}-.+\.md$", p.name), f"命名不符：{p.name}"
