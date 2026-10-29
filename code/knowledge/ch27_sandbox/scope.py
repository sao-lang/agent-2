"""读写范围分开：同一批路径，能读不等于能写。

运行：python code/knowledge/ch27_sandbox/scope.py
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent / ".demo-scope"
ROOT = BASE / "workspace"

READ_GLOBS = ("src/**", "tests/**", "*.md")
WRITE_GLOBS = ("src/**",)


def allowed(user_path: str, mode: str) -> tuple[bool, str]:
    target = (ROOT / user_path).resolve()
    if not target.is_relative_to(ROOT):
        return False, "路径越界"
    rel = target.relative_to(ROOT).as_posix()
    globs = WRITE_GLOBS if mode == "write" else READ_GLOBS
    # fnmatch 的 * 跨目录，与 shell 的通配不同：一个 "src/**" 就覆盖整棵子树
    if not any(fnmatch.fnmatch(rel, g) for g in globs):
        return False, f"不在 {'写' if mode == 'write' else '读'}白名单"
    return True, "放行"


def main() -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    (ROOT / "src").mkdir(parents=True)
    (ROOT / "tests").mkdir()
    (ROOT / ".git").mkdir()
    (ROOT / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (ROOT / "tests" / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (ROOT / "README.md").write_text("# demo\n", encoding="utf-8")
    (ROOT / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    print(f"=== 读白名单 {len(READ_GLOBS)} 条，写白名单 {len(WRITE_GLOBS)} 条 ===")
    cases = [
        ("read", "src/app.py"),
        ("write", "src/app.py"),
        ("read", "tests/test_app.py"),
        ("write", "tests/test_app.py"),
        ("read", "README.md"),
        ("write", "README.md"),
        ("read", ".git/config"),
        ("read", "../outside/x.txt"),
    ]
    for mode, path in cases:
        ok, reason = allowed(path, mode)
        print(f"  {mode:<5} {path:<20} {'放行' if ok else '拒绝：' + reason}")

    print()
    print("=== 收窄写范围的收益：同一批路径，能读不等于能写 ===")
    for path in ("tests/test_app.py", "README.md"):
        print(f"  {path}：读 {allowed(path, 'read')[0]}，写 {allowed(path, 'write')[0]}")
    print("  <- 2 条路径只有读权限；写范围比读范围窄是刻意的")
    shutil.rmtree(BASE, ignore_errors=True)


if __name__ == "__main__":
    main()
