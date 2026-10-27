"""命令守卫：白名单看命令名，路径层看参数里的路径，控制符看整条串。

不联网。两层判定叠在一起跑 9 条命令：
  命令层  首个 token 在白名单、没有 shell 包装、没有控制符、没有 -c
  路径层  参数里出现的路径必须在工作区之内
"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

ROOT = Path("_cmd_demo").resolve()
ALLOWED = {"pytest", "git", "ls", "cat", "python"}
SHELLS = {"sh", "bash", "cmd", "powershell", "pwsh"}
CONTROL = (";", "|", "&", ">", "<", "`", "$(")


def _looks_like_path(tok: str) -> bool:
    return any(ch in tok for ch in ("/", "\\")) and not tok.startswith("-")


def cmd_guard(cmd: str) -> str | None:
    toks = shlex.split(cmd)
    if not toks:
        return "空命令"
    head = toks[0]
    if head in SHELLS:
        return f"不允许用 shell 包一层：{head}"
    if head not in ALLOWED:
        return f"命令不在白名单：{head}"
    if any(ch in cmd for ch in CONTROL):
        return "含控制符（; | & > < ` $( ）"
    if head == "python" and "-c" in toks:
        return "python 不允许 -c（等于任意代码执行）"
    if head == "git" and any(t.startswith("--force") for t in toks):
        return "git --force 被拒绝"
    return None


def path_guard(cmd: str) -> str | None:
    for tok in shlex.split(cmd):
        if not _looks_like_path(tok):
            continue
        target = (ROOT / tok).resolve()
        if not target.is_relative_to(ROOT):
            return f"参数里的路径越界：{tok}"
    return None


CASES = [
    "pytest -q",
    "git status",
    "find . -delete",
    "sh -c 'rm -rf /'",
    "pytest -q; rm -rf build",
    "git push --force origin main",
    "cat ../../.ssh/id_rsa",
    "python -c \"print(open('/etc/passwd').read())\"",
    "python -m pytest -q",
]


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    print("=== 1. 两条守卫各自判什么 ===")
    rows = []
    for cmd in CASES:
        c = cmd_guard(cmd)
        p = path_guard(cmd)
        rows.append((cmd, c, p))
        print(f"  {cmd}")
        print(f"    命令层：{'拒绝 ' + c if c else '放行'}")
        print(f"    路径层：{'拒绝 ' + p if p else '放行'}")

    print()
    print("=== 2. 汇总：谁拦下了它 ===")
    both = sum(1 for _, c, p in rows if c or p)
    only_c = sum(1 for _, c, p in rows if c and not p)
    only_p = sum(1 for _, c, p in rows if p and not c)
    print(f"  {len(rows)} 条命令，拦下 {both} 条：命令层独拦 {only_c} 条，路径层独拦 {only_p} 条")
    print("  <- 只靠命令白名单会放过 cat ../../.ssh/id_rsa；只靠路径层会放过 sh -c 'rm -rf /'")

    print()
    print("=== 3. 白名单里放了 python 之后，-c 是一个缺口 ===")
    for cmd, c, _ in rows:
        if cmd.startswith("python -c"):
            print(f"  {cmd}")
            print(f"    没有 -c 规则时：放行（等待更下层的检查）")
            print(f"    加 -c 规则后： 拒绝 {c}")

    shutil.rmtree(ROOT)


if __name__ == "__main__":
    main()
