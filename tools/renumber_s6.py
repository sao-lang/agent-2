"""S6：删掉重复的旧 29/30 章后，把 31 及以后整体前移 2 位（--apply 才写盘）。

背景：
    新写的 09（分块与召回）与旧 29（分块与嵌入）是同一主题；
    新写的 10（检索优化与评测）与旧 30（检索优化）是同一主题。
    用户确认：删掉旧 29/30，独有知识点并入 09/10，**31 起整体 -2**。

映射规则：
    章号 N > 30  →  N - 2        （31→29, 32→30, …, 61→59）
    章号 N <= 30 →  不变
    文件里凡是 `## N.M`、`第 N 章`、`code/chNN_xxx` 三种形式都跟着改。

幂等设计：
    先把旧号换成 `~N~` 占位符，再把占位符换成新号。
    这样 31→29 与 29→27（假如有）不会互相踩 —— 本项目里 29/30 已删除，
    但我们仍然保留占位符机制，防止以后再有类似迁移时出错。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIFT_FROM = 31  # 从这一章开始 -2
SHIFT_BY = 2

# 代码目录：旧名 → 新名（只列会变的）
DIR_MAPPING: dict[str, str] = {
    "ch31_wiki": "ch29_wiki",
    "ch32_wiki_ops": "ch30_wiki_ops",
    "ch33_guardrails": "ch31_guardrails",
    "ch34_hitl": "ch32_hitl",
    "ch35_sandbox": "ch33_sandbox",
    "ch36_cost": "ch34_cost",
    "ch37_latency": "ch35_latency",
    "ch38_multi_agent": "ch36_multi_agent",
    "ch39_measuring": "ch37_measuring",
    "ch40_trace": "ch38_trace",
    "ch40_eval": "ch38_eval",
    "ch42_rag_eval": "ch40_rag_eval",
    "ch43_eval": "ch41_eval",
    "ch57_postmortem": "ch55_postmortem",
    "ch58_harness": "ch56_harness",
}

PENDING = "~{n}~"


def new_no(n: int) -> int:
    return n - SHIFT_BY if n >= SHIFT_FROM else n


def to_placeholder(text: str) -> str:
    """把所有"受影响的旧号"换成占位符。"""

    # ① `## N.M` 标题
    def _h(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"## {PENDING.format(n=n)}.{m.group(2)}" if n >= SHIFT_FROM else m.group(0)

    text = re.sub(r"^## (\d+)\.(\d+)", _h, text, flags=re.MULTILINE)

    # ② `第 N 章`
    def _c(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"第 {PENDING.format(n=n)} 章" if n >= SHIFT_FROM else m.group(0)

    text = re.sub(r"第 (\d+) 章", _c, text)

    # ③ `code/chNN_xxx` 路径
    def _p(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"code/ch{PENDING.format(n=n)}_{m.group(2)}" if n >= SHIFT_FROM else m.group(0)

    text = re.sub(r"code/ch(\d\d)_(\w+)", _p, text)

    # ④ 「第 N.4 节」这类小节引用
    def _s(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"第 {PENDING.format(n=n)}.{m.group(2)} 节" if n >= SHIFT_FROM else m.group(0)

    text = re.sub(r"第 (\d+)\.(\d+) 节", _s, text)

    # ⑤ markdown 链接里的 `NN-xxx.md`
    def _l(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return f"({PENDING.format(n=n)}-{m.group(2)})" if n >= SHIFT_FROM else m.group(0)

    text = re.sub(r"\((\d\d)-([^()]+?\.md)\)", _l, text)
    return text


def resolve(text: str) -> str:
    """把占位符换成真正的新号（补零到两位）。"""

    def _r(m: re.Match[str]) -> str:
        return f"{new_no(int(m.group(1))):02d}"

    return re.sub(r"~(\d+)~", _r, text)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写盘；默认只预演")
    args = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    md_files = sorted(p for p in ROOT.glob("*.md") if p.name[:2].isdigit())
    changed: list[tuple[str, int]] = []

    for p in md_files:
        original = p.read_text(encoding="utf-8")
        staged = to_placeholder(original)
        final = resolve(staged)
        if final != original:
            changed.append((p.name, len(re.findall(r"~\d+~", staged))))

    print(f"{'文件':<40}{'改动点数'}")
    print("-" * 56)
    for name, n in changed:
        print(f"{name:<40}{n}")
    print("-" * 56)
    print(f"共 {len(changed)} 个 md 文件需要改号")

    if not args.apply:
        print("\n（预演模式，未写盘。加 --apply 生效）")
        return 0

    for p in md_files:
        original = p.read_text(encoding="utf-8")
        final = resolve(to_placeholder(original))
        if final != original:
            p.write_text(final, encoding="utf-8")
    print("\n✅ 已写回")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
