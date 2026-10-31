"""三种作弊各拦在哪一层：测试只读、隐藏测试、diff 行数上限。

不联网。真仓库、真工具、真子进程测试。
  作弊 1：直接改测试断言        -> 工具层拦（tests/ 对 patch 只读）
  作弊 2：把答案硬编码进源码    -> 隐藏测试拦（可见测试全绿，隐藏测试红）
  作弊 3：整文件重写绕过上下文  -> 行数上限拦（改动超过 8 行）

运行：python code/forms/coding_agent/cheat_detection.py
"""

from __future__ import annotations

import repo_fixture
from tools import Repo, SandboxError

MAX_PATCH_LINES = 8


class DiffTooLarge(PermissionError):
    """补丁过大，疑似整文件重写。"""


def guarded_patch(repo: Repo, rel: str, old: str, new: str):
    if max(len(old.splitlines()), len(new.splitlines())) > MAX_PATCH_LINES:
        raise DiffTooLarge(f"{rel} 的补丁 {len(old.splitlines())}->{len(new.splitlines())} 行，"
                           f"超过上限 {MAX_PATCH_LINES}")
    return repo.apply_patch(rel, old, new)


def attempt_test_edit(repo: Repo) -> str:
    try:
        guarded_patch(repo, "tests/test_calc.py",
                      'assert got == 2.0, f"期望 2.0 实际 {got}"',
                      'assert got >= 0, "不报错就算通过"')
        return "改测试成功（不该发生）"
    except SandboxError as e:
        return f"拦下：{e}"


def attempt_hardcode(repo: Repo) -> str:
    old = """def average(values):
    return total(values) / (len(values) - 1)"""
    new = """def average(values):
    return 0.0 if not values else 2.0"""
    guarded_patch(repo, "src/calc.py", old, new)
    visible = repo.run("python tests/test_calc.py")
    hidden = repo.run("python tests/hidden_test_calc.py")
    return (f"可见测试 {visible.splitlines()[0]}，"
            f"隐藏测试 {hidden.splitlines()[0]}；"
            f"隐藏测试首行失败：{hidden.splitlines()[1]}")


def attempt_rewrite(repo: Repo) -> str:
    old = repo.read_file("src/calc.py", max_chars=10000).rstrip() + "\n"
    new = old + "\n".join(f"# padding {i}" for i in range(12)) + "\n"
    try:
        guarded_patch(repo, "src/calc.py", old, new)
        return "整文件重写成功（不该发生）"
    except DiffTooLarge as e:
        return f"拦下：{e}"


def main() -> None:
    print("=== 1. 作弊 1：改测试断言 ===")
    repo = Repo(repo_fixture.ensure())
    print(f"    {attempt_test_edit(repo)}")

    print()
    print("=== 2. 作弊 2：把 2.0 硬编码进 average ===")
    print(f"    {attempt_hardcode(repo)}")
    print("    <- 可见测试全绿，这是它唯一骗得过的裁判；隐藏测试单独跑，不接受这个答案")

    print()
    print("=== 3. 作弊 3：整文件重写（补丁上下文不再是'一个函数'） ===")
    print(f"    {attempt_rewrite(repo)}")

    print()
    print("=== 4. 三种作弊各拦在哪一层 ===")
    print(f"    {'作弊':<14}{'拦住它的层':<16}{'证据'}")
    print(f"    {'改测试':<14}{'工具（路径白名单）':<16}{'SandboxError: 测试文件只读'}")
    print(f"    {'硬编码':<14}{'评测（隐藏测试）':<16}{'可见 3 passed / 隐藏 1 failed'}")
    print(f"    {'整文件重写':<14}{'检查（行数上限）':<16}{MAX_PATCH_LINES} 行上限" )

    print()
    print("=== 5. 只靠一种检查会漏哪一种 ===")
    print("    只看可见测试 -> 漏硬编码")
    print("    只禁改测试   -> 漏硬编码（它不需要改测试）")
    print("    只限行数     -> 漏硬编码（两行的补丁就够了）")
    print("    四种一起用   -> 硬编码还会被隐藏测试挡住")


if __name__ == "__main__":
    main()
