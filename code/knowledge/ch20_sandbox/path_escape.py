"""路径边界：字符串前缀检查为什么拦不住，resolve() 之后为什么能拦。

不联网。示例在当前目录下造一个临时工作区：workspace/ 目录、名字相近的
兄弟目录 workspace-evil/、外部目录 outside/，然后把同一批用户输入分别
交给四种检查。

四种检查：
  v1  拼起来看字符串前缀（最常见的写法）
  v2  v1 加上分隔符（修掉"兄弟目录"这一种）
  v3  先 normpath 再比前缀（修掉遍历）
  v4  先 resolve 再判父子关系（is_relative_to）
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

BASE = Path("_sandbox_demo").resolve()
ROOT = BASE / "workspace"


def build_fixture() -> None:
    """造出对比用的目录结构。"""
    if BASE.exists():
        shutil.rmtree(BASE)
    ROOT.mkdir(parents=True)
    (ROOT / "notes.txt").write_text("允许读的文件", encoding="utf-8")
    (ROOT / "sub").mkdir()
    (ROOT / "sub" / "report.txt").write_text("子目录里的文件", encoding="utf-8")
    (BASE / "workspace-evil").mkdir()
    (BASE / "workspace-evil" / "x.txt").write_text("同名兄弟目录", encoding="utf-8")
    (BASE / "outside").mkdir()
    (BASE / "outside" / "secret.txt").write_text("不该被读到的内容", encoding="utf-8")
    # 符号链接需要特权（Windows 开发者模式 / root），失败就跳过
    try:
        os.symlink(BASE / "outside", ROOT / "link")
    except (OSError, NotImplementedError):
        pass
    # 硬链接不需要特权：root 里出现一个名字，内容是外部文件的
    try:
        os.link(BASE / "outside" / "secret.txt", ROOT / "hard.txt")
    except (OSError, NotImplementedError):
        pass


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


CHECKS = [
    ("v1", v1_prefix),
    ("v2", v2_prefix_sep),
    ("v3", v3_normpath),
    ("v4", v4_resolve),
]

# (显示用的输入, 真正喂给检查的输入)
ATTEMPTS = [
    ("notes.txt", "notes.txt"),
    ("sub/report.txt", "sub/report.txt"),
    ("../outside/secret.txt", "../outside/secret.txt"),
    ("sub/../../outside/secret.txt", "sub/../../outside/secret.txt"),
    ("/abs/outside/secret.txt", str(BASE / "outside" / "secret.txt")),
    ("..\\outside\\secret.txt", "..\\outside\\secret.txt"),
    ("/abs/workspace-evil/x.txt", str(BASE / "workspace-evil" / "x.txt")),
]


def show(path: Path) -> str:
    """输出用相对路径 + 正斜杠，避免打印机器的绝对路径与平台分隔符。"""
    try:
        rel = os.path.relpath(path, BASE)
    except ValueError:
        return str(path)
    rel = rel.replace(os.sep, "/")
    return rel


def inside(root: Path, target: Path) -> bool:
    return target.is_relative_to(root)


def where(root: Path, target: Path) -> str:
    """界内显示成 workspace/...，界外显示成 ../...。"""
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    return "workspace/" + rel if not rel.startswith("..") else rel


def main() -> None:
    build_fixture()

    print("=== 1. 同一批输入，四种检查的判定 ===")
    for label, value in ATTEMPTS:
        target = (ROOT / value).resolve()
        verdicts = "  ".join(f"{name} {'放行' if fn(ROOT, value) else '拒绝'}"
                             for name, fn in CHECKS)
        flag = "界内" if inside(ROOT, target) else "越界"
        print(f"  {label}")
        print(f"    {verdicts}   {flag} -> {where(ROOT, target)}")

    print()
    print("=== 2. 每修一次，放行越界的输入少几个 ===")
    for name, fn in CHECKS:
        bad = sum(1 for _, v in ATTEMPTS if fn(ROOT, v) and not (ROOT / v).resolve().is_relative_to(ROOT))
        print(f"  {name} 放行越界 {bad} / {len(ATTEMPTS)}")

    print()
    print("=== 3. 硬链接：四种检查全部放行，读到的仍是外部内容 ===")
    p = ROOT / "hard.txt"
    if p.exists():
        print(f"  v1..v4 判定：{all(fn(ROOT, 'hard.txt') for _, fn in CHECKS)}")
        print(f"  resolve 之后仍指向：workspace/{os.path.relpath(p.resolve(), ROOT)}")
        print(f"  读出来的是：{p.read_text(encoding='utf-8')}")
        print("  <- 路径检查约束的是名字，不是文件本身")

    print()
    print("=== 4. 同一份代码在两台机器上结论不同 ===")
    p = "sub\\report.txt"
    print(f"  输入 {p!r}")
    print(f"    Windows：反斜杠是分隔符，v4 判定 {v4_resolve(ROOT, p)}")
    print(f"    POSIX：反斜杠是文件名字符，同一个字符串指向另一个名字")
    if (ROOT / "link").exists():
        print(f"  符号链接 link/secret.txt：v3 {v3_normpath(ROOT, 'link/secret.txt')}，"
              f"v4 {v4_resolve(ROOT, 'link/secret.txt')}")

    shutil.rmtree(BASE)


if __name__ == "__main__":
    main()
