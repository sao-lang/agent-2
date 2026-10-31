"""编码 agent 的五个工具面：list_tree / read_file / search / apply_patch / run。

不联网。三个约束写在工具里，不写在提示词里：
  1 路径必须落在仓库根之内（resolve 之后比较前缀）
  2 tests/ 下的文件对 patch 只读（防"改测试而不是改代码"）
  3 run 只接受白名单命令，输出截断到 1200 字符

运行：python code/forms/coding_agent/tools.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TOKENS_PER_CHAR = 0.6
MAX_OUTPUT = 1200
ALLOWED = ("python tests/test_calc.py", "python tests/hidden_test_calc.py")


class SandboxError(PermissionError):
    """路径越界。"""


class ToolResult(str):
    """工具返回一段文本，附带本次消耗的估算 token。"""

    tokens: int

    def __new__(cls, text: str, tokens: int = 0):
        obj = super().__new__(cls, text)
        obj.tokens = tokens
        return obj


def _count(text: str) -> int:
    return int(len(text) * TOKENS_PER_CHAR)


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root != p and self.root not in p.parents:
            raise SandboxError(f"路径越界：{rel}")
        return p

    # 1 列目录
    def list_tree(self, prefix: str = ".") -> ToolResult:
        base = self._resolve(prefix)
        files = sorted(str(p.relative_to(self.root)).replace("\\", "/")
                       for p in base.rglob("*") if p.is_file())
        text = "\n".join(files)
        return ToolResult(text, _count(text))

    # 2 读文件
    def read_file(self, rel: str, max_chars: int = 3000) -> ToolResult:
        text = self._resolve(rel).read_text("utf-8")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n[截断，原长 {len(text)} 字符]"
        return ToolResult(text, _count(text))

    # 3 搜索
    def search(self, pattern: str, glob: str = "*.py", limit: int = 20) -> ToolResult:
        hits = []
        for p in sorted(self.root.rglob(glob)):
            if not p.is_file():
                continue
            for i, line in enumerate(p.read_text("utf-8").splitlines(), 1):
                if re.search(pattern, line):
                    rel = str(p.relative_to(self.root)).replace("\\", "/")
                    hits.append(f"{rel}:{i}: {line.strip()}")
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit:
                break
        text = "\n".join(hits) or "没有命中"
        return ToolResult(text, _count(text))

    # 4 打补丁（不是整文件写回）
    def apply_patch(self, rel: str, old: str, new: str) -> ToolResult:
        p = self._resolve(rel)
        if rel.replace("\\", "/").startswith("tests/"):
            raise SandboxError(f"{rel} 是测试文件，patch 只读")
        text = p.read_text("utf-8")
        if text.count(old) != 1:
            raise ValueError(f"补丁上下文必须唯一命中，实际命中 {text.count(old)} 次")
        p.write_text(text.replace(old, new), encoding="utf-8")
        plus = len(new.splitlines())
        minus = len(old.splitlines())
        msg = f"已应用 {rel}（+{plus} -{minus}）"
        return ToolResult(msg, _count(msg))

    # 5 跑命令
    def run(self, cmd: str) -> ToolResult:
        if not cmd.startswith(ALLOWED):
            raise SandboxError(f"命令不在白名单：{cmd}")
        proc = subprocess.run(cmd, cwd=self.root, shell=True, capture_output=True,
                              text=True, timeout=20)
        out = (proc.stdout + proc.stderr).strip()
        if len(out) > MAX_OUTPUT:
            out = out[:MAX_OUTPUT] + "\n[截断]"
        text = f"exit={proc.returncode}\n{out}"
        return ToolResult(text, _count(text))


def demo(root: Path) -> None:
    repo = Repo(root)
    print("=== 1. list_tree ===")
    print("    " + str(repo.list_tree()).replace("\n", "\n    "))

    print()
    print("=== 2. read_file(src/calc.py) ===")
    print("    " + str(repo.read_file("src/calc.py")).replace("\n", "\n    "))

    print()
    print("=== 3. search('len\\\\(values\\\\)') ===")
    print("    " + str(repo.search(r"len\(values\)")).replace("\n", "\n    "))

    print()
    print("=== 4. 越界与只读两条边界 ===")
    for call in (lambda: repo.read_file("../outside.txt"),
                 lambda: repo.apply_patch("tests/test_calc.py", "== 2.0", ">= 0")):
        try:
            call()
        except Exception as e:                      # noqa: BLE001 演示用
            print(f"    {type(e).__name__}: {e}")

    print()
    print("=== 5. run 白名单 ===")
    try:
        repo.run("python -c \"print(1)\"")
    except Exception as e:                          # noqa: BLE001 演示用
        print(f"    {type(e).__name__}: {e}")
    print("    " + str(repo.run("python tests/test_calc.py")).replace("\n", "\n    "))


if __name__ == "__main__":
    import repo_fixture

    demo(repo_fixture.ensure())
