#!/usr/bin/env python3
"""核对改写前后的不可触碰清单（见 docs/REFACTOR-v12-精简.md 第三节）。

用法：
    python docs/trim_verify.py 01 --base HEAD          # 对比 git 里的旧版
    python docs/trim_verify.py 01 --base path/old.md   # 对比指定文件

检查项：
    1. 代码块 / 输出块逐字一致（哈希）
    2. 标题集合与顺序一致
    3. 表格块逐字一致
    4. 章首引用块、章末清单、导航行一致
    5. 第 N 章引用、code/ 路径、相对链接只增不减
    6. 知识点词表（章内 H3 标题里的名词 + book.json 的 points 中文名）仍然出现
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "docs" / "book.json"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def fences(text: str) -> list[str]:
    return [b.strip() for b in re.findall(r"```.*?```", text, flags=re.S)]


def tables(text: str) -> list[str]:
    out, cur = [], []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            cur.append(line)
        elif cur:
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def headings(text: str) -> list[str]:
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    return [m.group(0).strip() for m in re.finditer(r"^#{1,6} .*$", body, flags=re.M)]


def head_block(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(l for l in lines[:12] if l.startswith(">"))


def tail_block(text: str) -> str:
    i = text.find("## 这一章建立的")
    return text[i:] if i >= 0 else ""


def refs(text: str) -> dict[str, int]:
    return {
        "第N章": len(re.findall(r"第 ?\d{1,2} ?章", text)),
        "code路径": len(re.findall(r"code/[\w\-./]+", text)),
        "相对链接": len(re.findall(r"\]\(\./", text)),
    }


def point_names(stem: str, base_text: str, with_headings: bool = True) -> list[str]:
    """知识点词表：book.json 的中文名 + 原文章节里的 H3 标题名词。"""
    names: list[str] = []
    try:
        data = json.loads(BOOK.read_text(encoding="utf-8"))
        no = int(stem)
        ch = next(c for c in data["chapters"] if c["no"] == no)
        for pid in ch["points"]:
            p = data["_point"][pid]
            names.append(p.get("name") or p.get("title") or "")
    except Exception:
        pass
    if with_headings:                     # 严格模式才拿小节标题当知识点代理
        for h in headings(base_text):
            if h.startswith("###"):
                names.append(re.sub(r"^#+\s*\d+(\.\d+)*\s*", "", h).strip())
    return [n for n in (x.strip() for x in names) if n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--new", default=None)
    ap.add_argument("--allow-head", action="store_true",
                    help="章首引用块允许与基线不同（由 book.json / check_nav 负责）")
    ap.add_argument("--allow-tail", action="store_true",
                    help="允许改章末清单的措辞（条目数与导航行不变）")
    ap.add_argument("--restructure", action="store_true",
                    help="允许改小节标题（合并 / 重编号），其余不变")
    args = ap.parse_args()

    if args.new:
        new_path = Path(args.new)
    else:
        new_path = next(p for p in ROOT.glob(f"{args.stem}-*.md"))
    new_text = new_path.read_text(encoding="utf-8")

    # 基线一律取仓库里的那一章（不是 .trim/ 下的中间产物）
    chapter = next(p for p in ROOT.glob(f"{args.stem}-*.md"))
    if Path(args.base).exists():
        base_text = Path(args.base).read_text(encoding="utf-8")
    else:
        # 其余情况都当 git 修订处理：HEAD、HEAD~1、提交号
        base_text = ""
        # ① 先按当前文件名取
        base_text = subprocess.run(
            ["git", "show", f"{args.base}:{chapter.name}"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8").stdout
        if not base_text.strip():
            # ② 文件名在该提交之后改过：按章号在基线树里找
            tree = subprocess.run(["git", "-c", "core.quotepath=false",
                                   "ls-tree", "--name-only", args.base],
                                  cwd=ROOT, capture_output=True, text=True,
                                  encoding="utf-8").stdout.splitlines()
            cand = [n for n in tree if n.startswith(f"{args.stem}-") and n.endswith(".md")]
            if cand:
                base_text = subprocess.run(
                    ["git", "show", f"{args.base}:{cand[0]}"], cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8").stdout
                print(f"  基线文件名已变更，改用 {cand[0]}")

    if not base_text.strip():
        print("取不到基线文本", file=sys.stderr)
        return 2

    bad: list[str] = []

    if [sha(x) for x in fences(base_text)] != [sha(x) for x in fences(new_text)]:
        n0, n1 = len(fences(base_text)), len(fences(new_text))
        bad.append(f"代码/输出块不一致（{n0} → {n1} 块）")

    hb, hn = headings(base_text), headings(new_text)
    if hb != hn:
        if args.restructure:
            print(f"  标题由 {len(hb)} 条变为 {len(hn)} 条（--restructure 允许）")
        else:
            b, n = set(hb), set(hn)
            bad.append(f"标题不一致：缺失 {sorted(b - n)} 新增 {sorted(n - b)}")

    if [sha(t) for t in tables(base_text)] != [sha(t) for t in tables(new_text)]:
        bad.append("表格块不一致")

    if head_block(base_text) != head_block(new_text):
        if args.allow_head:
            print("  章首引用块有差异（--allow-head 允许，由 check_nav 校验 book.json 一致性）")
        else:
            bad.append("章首引用块不一致")

    tb, tn = tail_block(base_text), tail_block(new_text)
    if tb != tn:
        if args.allow_tail:
            mb = re.search(r"## 这一章建立的 (\d+) 件事", tb)
            mn = re.search(r"## 这一章建立的 (\d+) 件事", tn)
            if not (mb and mn and mb.group(1) == mn.group(1)):
                bad.append("章末清单条目数不一致")
            nav_n = [l for l in tn.splitlines() if "｜" in l]
            if len(nav_n) != 1 or nav_n[0].count("](") < 3:
                bad.append("章末导航行缺失或链接数不对")
            print("  章末清单措辞有改动（--allow-tail 允许，条目数与导航一致）")
        else:
            bad.append("章末清单 / 下一章 / 导航不一致")

    rb, rn = refs(base_text), refs(new_text)
    for k in rb:
        if rn[k] < rb[k]:
            bad.append(f"{k} 减少：{rb[k]} → {rn[k]}")

    for name in point_names(args.stem, base_text, not args.restructure):
        if name and name not in new_text:
            bad.append(f"知识点名词消失：{name}")

    zh0 = len(re.findall(r"[\u4e00-\u9fff]", base_text))
    zh1 = len(re.findall(r"[\u4e00-\u9fff]", new_text))
    print(f"{new_path.name}: 汉字 {zh0} → {zh1}（{(zh1 - zh0) / zh0:+.0%}）")
    if bad:
        print(f"FAIL  不通过 {len(bad)} 项")
        for b in bad:
            print(f"  - {b}")
        return 1
    print("PASS  不可触碰清单全部一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
