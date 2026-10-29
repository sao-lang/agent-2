"""四种路径检查写法，在同一批输入上的对照。

运行：python code/knowledge/ch27_sandbox/path_checks.py
示例在脚本目录下自建 workspace/ 与 outside/，不读系统临时目录。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent / ".demo"
ROOT = BASE / "workspace"


def v1_prefix(root: Path, user_path: str) -> bool:
    """v1：拼起来，看字符串前缀。"""
    full = os.path.join(str(root), user_path)
    return full.startswith(str(root))


def v2_prefix_sep(root: Path, user_path: str) -> bool:
    """v2：前缀后面要求一个分隔符。"""
    full = os.path.join(str(root), user_path)
    return full.startswith(str(root) + os.sep)


def v3_normpath(root: Path, user_path: str) -> bool:
    """v3：先做字面规范化，再比前缀。"""
    full = os.path.normpath(os.path.join(str(root), user_path))
    return full.startswith(str(root) + os.sep)


def v4_resolve(root: Path, user_path: str) -> bool:
    """v4：解析成真实路径，再判它是不是在 root 之下。"""
    try:
        full = (root / user_path).resolve()
    except (OSError, RuntimeError):
        return False
    return full.is_relative_to(root)


CHECKS = (("v1", v1_prefix), ("v2", v2_prefix_sep), ("v3", v3_normpath), ("v4", v4_resolve))


def make_layout() -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    (ROOT / "sub").mkdir(parents=True)
    (BASE / "outside").mkdir()
    (BASE / "workspace-evil").mkdir()

    (ROOT / "notes.txt").write_text("界内笔记", encoding="utf-8")
    (ROOT / "sub" / "report.txt").write_text("界内报告", encoding="utf-8")
    (BASE / "outside" / "secret.txt").write_text("外部秘密", encoding="utf-8")
    (BASE / "workspace-evil" / "x.txt").write_text("同名前缀的兄弟目录", encoding="utf-8")


def display(target: Path) -> str:
    try:
        return target.relative_to(BASE).as_posix()
    except ValueError:
        return str(target)


def run_table(attempts: list[tuple[str, str]]) -> None:
    print("=== 1. 同一批输入，四种检查的判定 ===")
    escape_counts = {name: 0 for name, _ in CHECKS}
    for label, user_path in attempts:
        target = (ROOT / user_path).resolve()
        inside = target.is_relative_to(ROOT)
        marks = []
        for name, fn in CHECKS:
            allowed = fn(ROOT, user_path)
            marks.append(f"{name} {'放行' if allowed else '拒绝'}")
            if allowed and not inside:
                escape_counts[name] += 1
        verdict = "界内" if inside else "越界"
        print(f"  {label}")
        print(f"    {'  '.join(marks)}   {verdict} -> {display(target)}")

    print()
    print("=== 2. 每修一次，放行越界的输入少几个 ===")
    total = sum(1 for _, p in attempts if not (ROOT / p).resolve().is_relative_to(ROOT))
    for name, _ in CHECKS:
        print(f"  {name} 放行越界 {escape_counts[name]} / {total}")


def try_dir_link(link: Path, target: Path) -> str:
    """先试符号链接，失败时在 Windows 上用目录联接（Junction）。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return "符号链接"
    except (OSError, NotImplementedError):
        if os.name == "nt":
            proc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return "目录联接"
        raise


def run_links() -> None:
    print()
    print("=== 3. 链接：normpath 看不见，resolve 看得见 ===")
    link = ROOT / "out-link"
    kind = try_dir_link(link, BASE / "outside")
    linked = link / "secret.txt"
    print(f"  {kind} out-link -> outside")
    print(f"    v3 判定 {v3_normpath(ROOT, 'out-link/secret.txt')}（字符串仍在 root 下）")
    print(f"    v4 判定 {v4_resolve(ROOT, 'out-link/secret.txt')}（解析到 {display(linked.resolve())}）")

    hard = ROOT / "hard.txt"
    os.link(BASE / "outside" / "secret.txt", hard)
    print("  硬链接 hard.txt -> outside/secret.txt")
    print(f"    v4 判定 {v4_resolve(ROOT, 'hard.txt')}，resolve 后仍在 root 下")
    print(f"    读出来：{hard.read_text(encoding='utf-8')}")
    print("    <- 路径边界管名字，管不住文件的第二个名字")

    if link.exists():
        os.rmdir(link)


def main() -> None:
    make_layout()
    attempts = [
        ("notes.txt", "notes.txt"),
        ("sub/report.txt", "sub/report.txt"),
        ("../outside/secret.txt", "../outside/secret.txt"),
        ("sub/../../outside/secret.txt", "sub/../../outside/secret.txt"),
        ("绝对路径 outside/secret.txt", str(BASE / "outside" / "secret.txt")),
        (r"..\outside\secret.txt", r"..\outside\secret.txt"),
        ("../workspace-evil/x.txt", "../workspace-evil/x.txt"),
        ("绝对路径 workspace-evil/x.txt", str(BASE / "workspace-evil" / "x.txt")),
    ]
    try:
        run_table(attempts)
        run_links()
    finally:
        shutil.rmtree(BASE, ignore_errors=True)


if __name__ == "__main__":
    main()
