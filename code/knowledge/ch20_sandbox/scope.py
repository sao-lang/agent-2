"""读范围与写范围分开：同一条路径，读放行不代表写也放行。

不联网。两个白名单按相对路径的形态匹配：
  读  src/**、tests/**、*.md
  写  只有 src/**
边界只有一条时，一个只需要"看测试"的 agent 也能改测试，它就可以把失败的
用例改成通过的。
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path

ROOT = Path("_scope_demo").resolve()
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


CASES = [
    ("read", "src/app.py"),
    ("write", "src/app.py"),
    ("read", "tests/test_app.py"),
    ("write", "tests/test_app.py"),
    ("read", "README.md"),
    ("write", "README.md"),
    ("read", ".git/config"),
    ("read", "../outside/x.txt"),
]


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "src").mkdir(parents=True)
    (ROOT / "tests").mkdir()
    (ROOT / "README.md").write_text("说明", encoding="utf-8")

    print("=== 读白名单 3 条，写白名单 1 条 ===")
    for mode, p in CASES:
        ok, why = allowed(p, mode)
        print(f"  {mode:<5} {p:<22} {'放行' if ok else '拒绝：' + why}")

    print()
    print("=== 收窄写范围的收益：同一批路径，能读不等于能写 ===")
    paths = list(dict.fromkeys(p for _, p in CASES))
    diff = [p for p in paths if allowed(p, "read")[0] != allowed(p, "write")[0]]
    for p in diff:
        print(f"  {p}：读 {allowed(p, 'read')[0]}，写 {allowed(p, 'write')[0]}")
    print(f"  <- {len(diff)} 条路径只有读权限；写范围比读范围窄是刻意的")

    shutil.rmtree(ROOT)


if __name__ == "__main__":
    main()
