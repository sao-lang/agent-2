"""Skill 目录树、三级加载的 token 占用、L3 脚本与单测。

不联网（tiktoken 首次运行会下载 cl100k_base 词表，约 1.7MB）。

运行：python code/knowledge/ch26_skills/skill_layout.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import tiktoken

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "skills")
SKILL = os.path.join(SKILLS, "refund-review")

ENC = tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    return len(ENC.encode(text))


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


SKIP = {"__pycache__", ".pytest_cache"}


def tree(root: str) -> None:
    """递归打印目录树，每个文件后面跟字符数。"""
    print(os.path.basename(root) + "/")

    def walk(path: str, prefix: str) -> None:
        names = [n for n in sorted(os.listdir(path)) if n not in SKIP]
        dirs = [n for n in names if os.path.isdir(os.path.join(path, n))]
        files = [n for n in names if os.path.isfile(os.path.join(path, n))]
        items = [(n, True) for n in dirs] + [(n, False) for n in files]
        for i, (name, is_dir) in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            if is_dir:
                print(f"{prefix}{branch}{name}/")
                walk(os.path.join(path, name), prefix + ("    " if last else "│   "))
            else:
                size = len(read(os.path.join(path, name)))
                print(f"{prefix}{branch}{name:<{20 - len(prefix)}}{size:>6} 字符")

    walk(root, "")


def frontmatter(text: str) -> str:
    """SKILL.md 开头 --- 之间的部分，就是常驻的元数据。"""
    body = text.split("---", 2)
    return body[1] if len(body) >= 3 else text


def measure(root: str) -> dict:
    skill_md = read(os.path.join(root, "SKILL.md"))
    l1 = tokens(frontmatter(skill_md))
    l2 = tokens(skill_md)
    total = 0
    files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for f in filenames:
            total += tokens(read(os.path.join(dirpath, f)))
            files += 1
    return {"L1": l1, "L2": l2, "L3": total, "files": files}


def run_l3_script() -> None:
    """L3 的 scripts/ 被真正执行一次：先跑单测，再用脚本校验一条结论。"""
    tests = subprocess.run(
        [sys.executable, os.path.join(SKILL, "tests", "test_check.py")],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    print("  tests/test_check.py ->", (tests.stderr or "").strip().splitlines()[-1])

    good = {"order_id": "A1001", "signed_days_ago": 3, "window_days": 7,
            "conclusion": "可退", "clause": "第四条"}
    bad = {"order_id": "A1001", "signed_days_ago": 9, "window_days": 7,
           "conclusion": "可退", "clause": "第四条"}
    for label, rec in (("一致的结论", good), ("矛盾的结论", bad)):
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "scripts", "check.py"),
             json.dumps(rec, ensure_ascii=False)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        print(f"  {label} -> exit={r.returncode}  {r.stdout.strip()}")


def check_skill_tools(skill_text: str, visible: list[str]) -> list[str]:
    """SKILL.md 正文里提到的工具名，是否都在激活时的可见集里。"""
    mentioned = set(re.findall(r"[a-z]+__[a-z_]+", skill_text))
    return sorted(mentioned - set(visible))


def width(s: str) -> int:
    """终端显示宽度：汉字算 2 列。"""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - width(s))


def main() -> None:
    print("=== 1. 一个完整 Skill 的目录树 ===")
    tree(SKILL)

    m = measure(SKILL)
    print()
    print("=== 2. 三级加载的 token 占用（cl100k_base）===")
    print(f"  L1 元数据常驻（frontmatter）      {m['L1']:>5} token")
    print(f"  L2 命中后加载（SKILL.md 全文）    {m['L2']:>5} token")
    print(f"  L3 资源全读（{m['files']} 个文件）          {m['L3']:>5} token")
    print(f"  L3 / L1 = {m['L3'] / m['L1']:.1f} 倍；L3 / L2 = {m['L3'] / m['L2']:.1f} 倍")
    print("  命中一套时 = 十套 L1 + 一套 L2 + 这次真正读到的 L3")

    n = 10
    print()
    print("=== 3. 十套流程两种供给方式的常驻开销 ===")
    print(f"  全部写进系统提示词        {n * m['L2']:>6} token（十套正文全部常驻）")
    print(f"  三级加载，无命中          {n * m['L1']:>6} token（十套只留元数据）")
    print(f"  三级加载，命中一套        {n * m['L1'] + m['L2']:>6} token（十套元数据 + 一套正文）")
    print(f"  差一个量级：{n * m['L2'] / (n * m['L1']):.1f} 倍，命中也只多一套正文")

    print()
    print("=== 4. L3 的脚本被执行一次 ===")
    run_l3_script()

    print()
    print("=== 5. Skill 引用的工具是否都可见 ===")
    body = read(os.path.join(SKILL, "SKILL.md"))
    for stage, vis in (
        ("退货判定", ["order__get_order", "order__get_policy", "order__refund_apply"]),
        ("查订单", ["order__get_order", "order__search"]),
    ):
        missing = check_skill_tools(body, vis)
        print(f"  {pad(stage, 10)}缺：{missing if missing else '无'}")


if __name__ == "__main__":
    main()
