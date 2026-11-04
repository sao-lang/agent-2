"""渐进式披露：同一个 skill，三个加载级别各付多少。

L1 只读 frontmatter（常驻），L2 命中后读 SKILL.md 正文，L3 走到哪一步读哪一份资料。
不联网；决策脚本是本地的 decide.py。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).with_name("skills") / "refund-review"
TRIGGERS = ("退货", "能退", "退款", "七天", "签收")


def tokens(text: str) -> int:
    """粗估 token：汉字按 1、其他按 0.25。只为比较量级。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


def split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, flags=re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def main() -> None:
    raw = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    front, body = split_frontmatter(raw)

    print("=== L1：常驻的元数据 ===")
    name = re.search(r"^name:\s*(.+)$", front, flags=re.M).group(1)
    desc = re.search(r"^description:\s*(.+)$", front, flags=re.M).group(1)
    print(f"  name={name}  description {len(desc)} 字 ≈ {tokens(front)} token（含全部前置项）")

    question = "订单 A1002 签收 9 天了，还能退吗？"
    hits = [w for w in TRIGGERS if w in question]
    print(f"  问题：{question}")
    print(f"  命中触发词 {hits} -> 进入 L2；没命中就不读正文，L1 的代价到此为止")

    print("=== L2：命中后读正文 ===")
    print(f"  SKILL.md 正文 {len(body)} 字 ≈ {tokens(body)} token")
    steps = len(re.findall(r"^\d+\. ", body, flags=re.M))
    refs = len(re.findall(r"`references/[^`]+`", body))
    scripts = len(re.findall(r"`scripts/[^`]+`", body))
    print(f"  正文里：编号步骤 {steps} 条（前置 3 + 执行 6）、资料名 {refs} 处、脚本名 {scripts} 个（只读了名字，没读内容）")

    print("=== L3：走到第 4 步，只读一份资料 ===")
    exc = (SKILL / "references" / "exception.md").read_text(encoding="utf-8")
    print(f"  references/exception.md {len(exc)} 字 ≈ {tokens(exc)} token")

    print("=== L3：走到第 5 步，跑一次脚本 ===")
    record = {"order_id": "A1002", "signed_days_ago": 9, "category": "普通"}
    proc = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "decide.py"), json.dumps(record, ensure_ascii=False)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print("  decide.py ->", proc.stdout.strip())
    print("  退出码", proc.returncode, "（0 表示判定成立）")

    print("=== 对比：全量读 vs 三级按需 ===")
    everything = raw
    for p in sorted((SKILL / "references").glob("*.md")):
        everything += p.read_text(encoding="utf-8")
    for p in sorted((SKILL / "scripts").glob("*.py")):
        everything += p.read_text(encoding="utf-8")
    for p in sorted((SKILL / "tests").glob("*.py")):
        everything += p.read_text(encoding="utf-8")

    full = tokens(everything)
    staged = tokens(front) + tokens(body) + tokens(exc)
    print(f"  全量读入（正文 + 3 份资料 + 脚本 + 测试）≈ {full} token")
    print(f"  三级按需（L1 + L2 + 一份资料）≈ {staged} token")
    print(f"  这一次省下 ≈ {full - staged} token，且资料越多、省得越多")


if __name__ == "__main__":
    main()
