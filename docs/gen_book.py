#!/usr/bin/env python3
"""从 book.json 生成 INDEX.md，并维护各章的章首元信息与章末导航。

用法：
    python docs/gen_book.py index          # 只重新生成 INDEX.md
    python docs/gen_book.py build          # 生成 INDEX.md，并改写已写章节的章首/章末
    python docs/gen_book.py build --dry    # 只打印将要发生的改动

约定（改动前先读 docs/WRITING-SPEC.md 第 1.4 节）：
  * book.json 是唯一事实源：卷、章、知识点、状态、落点计划都在这里。
  * 文件名 = 章号 + 标题（空格与引号去掉，：，、统一换成 -）。
  * 生成是幂等的：重复运行不会叠加内容。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "book.json"

POINT_FILE = {
    "A": "outline/11-知识点-A-模型层.md",
    "B": "outline/12-知识点-B-运行层.md",
    "C": "outline/13-知识点-C-知识层.md",
    "D": "outline/14-知识点-D-约束层.md",
    "E": "outline/15-知识点-E-度量层.md",
    "F": "outline/16-知识点-F-框架层.md",
    "H": "outline/17-知识点-H-工具与评测平台.md",
    "G": "outline/18-知识点-G-深水区.md",
}
GROUP_ORDER = ["A", "B", "C", "D", "E", "F", "H", "G"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 基础查询

def load() -> dict:
    data = json.loads(BOOK.read_text(encoding="utf-8"))
    data["_by_no"] = {c["no"]: c for c in data["chapters"]}
    data["_point"] = {p["id"]: p for p in data["points"]}
    data["_vol"] = {}
    for v in data["volumes"]:
        for no in v["chapters"]:
            data["_vol"][no] = v
    return data


def fname(ch: dict) -> str:
    """章号 + 标题 → 文件名。"""
    t = ch["title"]
    for a in (" ", "\u3000", "“", "”", "`", '"'):
        t = t.replace(a, "")
    for a in ("：", "，", "、"):
        t = t.replace(a, "-")
    return f"{ch['no']:02d}-{t}.md"


def norm_title(t: str) -> str:
    """标题归一化：去掉所有空白与引号，用于文件名与 H1 的对照。"""
    return re.sub(r"[\s\"'“”‘’`]+", "", t)


def vrange(vol: dict) -> str:
    ch = vol["chapters"]
    if len(ch) == 1:
        return f"第 {ch[0]} 章"
    return f"第 {ch[0]}–{ch[-1]} 章"


def body_url(path: str) -> str:
    return "./" + path


# ---------------------------------------------------------------- 章首/章末

def point_line(ch: dict, data: dict) -> str:
    if not ch["points"]:
        return "**知识点**：无（本章只建立全书的地图，不承载 A–G 中的任何一条）"
    notes = ch.get("notes", {})
    glosses = ch.get("glosses", {})
    parts = []
    files = []
    for pid in ch["points"]:
        p = data["_point"][pid]
        note = notes.get(pid, "")
        head = f"{pid}{note}" if note else f"{pid} {p['name']}"
        gloss = glosses.get(pid, p["gloss"])
        parts.append(f"{head} —— {gloss}")
        f = POINT_FILE[pid[0]]
        if f not in files:
            files.append(f)
    refs = "、".join(f"[{Path(f).stem.split('-', 1)[1]}]({body_url(f)})" for f in files)
    return f"**知识点**：{'；'.join(parts)}（编号定义见 {refs}）"


def vol_line(ch: dict, data: dict) -> str:
    vol = data["_vol"][ch["no"]]
    return (f"**卷 {vol['no']} · {vol['name']}（{vrange(vol)}）**"
            f"｜[全书目录](./INDEX.md#vol{vol['no']})"
            f"｜[本卷导读]({body_url(vol['file'])})")


def quote_item(line: str) -> str:
    """把旧格式 `> **本章回答**：…` 或新格式 `> - …` 还原成纯文本。"""
    text = line[1:].lstrip() if line.startswith(">") else line
    if text.startswith("- "):
        text = text[2:].lstrip()
    return text


def nav_line(ch: dict, data: dict) -> str:
    vol = data["_vol"][ch["no"]]
    parts = []
    prev = data["_by_no"].get(ch["no"] - 1)
    if prev:
        parts.append(f"[← 第 {prev['no']} 章 · {prev['title']}](./{fname(prev)})")
    else:
        parts.append("[全书目录](./INDEX.md)")
    parts.append(f"[卷 {vol['no']} 目录](./INDEX.md#vol{vol['no']})")
    nxt = data["_by_no"].get(ch["no"] + 1)
    if nxt is None:
        parts.append("[全书目录](./INDEX.md)")
    elif nxt["status"] == "done":
        parts.append(f"[第 {nxt['no']} 章 · {nxt['title']} →](./{fname(nxt)})")
    else:
        v2 = data["_vol"][nxt["no"]]
        parts.append(f"第 {nxt['no']} 章 · {nxt['title']}（卷 {v2['no']}，待写）"
                     f"→ [章节计划]({body_url(nxt['plan'])})")
    return "　｜　".join(parts)


def patch_chapter(text: str, ch: dict, data: dict) -> str:
    lines = text.replace("\r\n", "\n").split("\n")

    # 章首：H1 之后连续的引用块整块重建，保留原有的“本章回答/示例/读完”行。
    # 元信息放进引用块里的列表：CommonMark 只有在列表项之间才保证换行，
    # 连续 `> **标签**：…` 会被软换行合并成一段（预览里五行挤成一行）。
    i = next(k for k, l in enumerate(lines) if l.startswith("# "))
    j = i + 1
    while j < len(lines) and (not lines[j].strip() or lines[j].startswith(">")):
        j += 1
    keep = []
    for line in lines[i + 1:j]:
        if not line.startswith(">") or "**知识点**" in line:
            continue
        if not line.strip() or line.startswith("> **卷 ") or "**本章不负责**" in line:
            continue
        item = quote_item(line)
        if item:
            keep.append(item)
    block = ["", f"> {vol_line(ch, data)}", ">", f"> - {point_line(ch, data)}"]
    block += [f"> - {item}" for item in keep]
    if ch.get("boundary"):
        block.append(f"> - **本章不负责**：{ch['boundary']}")
    block.append("")
    if j >= len(lines) or lines[j].strip() != "---":
        block += ["---", ""]
    lines = lines[:i + 1] + block + lines[j:]

    # 章末：在「## 下一章」之后补一段机器导航；重复运行先删旧块
    k = max(k for k, l in enumerate(lines) if l.strip() == "## 下一章")
    tail = lines[k + 1:]
    while tail and not tail[-1].strip():
        tail.pop()
    if tail and tail[-1].startswith("["):
        tail.pop()
        while tail and not tail[-1].strip():
            tail.pop()
        if tail and tail[-1].strip() == "---":
            tail.pop()
            while tail and not tail[-1].strip():
                tail.pop()
    tail += ["", "---", "", nav_line(ch, data), ""]
    lines = lines[:k + 1] + tail
    return "\n".join(lines)


# ---------------------------------------------------------------- INDEX.md

def render_index(data: dict) -> str:
    done = [c for c in data["chapters"] if c["status"] == "done"]
    out: list[str] = []
    a = out.append

    a(f"# 《{data['title']}》全书目录")
    a("")
    a(f"> 13 卷、58 章（第 0–57 章）、108 条知识点。**已写第 0–{done[-1]['no']} 章**，"
      f"第 {done[-1]['no'] + 1} 章起待写。")
    a(">")
    a("> 本文件由 `python docs/gen_book.py index` 从 [`book.json`](./book.json) 生成，不要手改。")
    a("> 章节结构见 [OUTLINE.md](./OUTLINE.md)，知识点定义见 [outline/](./outline/)，"
      "写法见 [docs/WRITING-SPEC.md](./docs/WRITING-SPEC.md)。")
    a("")
    a("## 怎么用这份目录")
    a("")
    a("- 顺序读：从[第 0 章](./00-agent的差别.md)开始；每章末尾都有「上一章 ｜ 卷目录 ｜ 下一章」。")
    a("- 查一个知识点在哪讲：看[知识点索引](#points)。")
    a("- 查文件与章号的对应：看[文件名对照](#files)。")
    a("- 查某一卷讲什么：看下面每一卷的「本卷回答」与卷表。")
    a("")
    a("## 阅读路径")
    a("")
    a("| 目标 | 读哪些 |")
    a("|---|---|")
    a("| 只想尽快做出一个能用的 | 第 0 章 → 卷 1 → 卷 2 → 卷 3 |")
    a("| 想自己写一个能跑的 | 第 0 章 → 卷 1 → 卷 2 → 卷 4 → 卷 5 |")
    a("| 交付一个能上线的 | 第 0 章 → 卷 1–7 → 卷 10 → 第 51 章 |")
    a("| 理解框架为什么这么设计 | 全书主线 → 卷 8 → 卷 12 |")
    a("| 拿到一个项目，要定架构 | 第 22 章 → 第 51 章 |")
    a("")
    a("卷 1 是唯一跳过之后后面全看不懂的一卷；卷 12 是唯一可以整卷跳过的。")
    a("")

    for vol in data["volumes"]:
        a(f'<a id="vol{vol["no"]}"></a>')
        a("")
        a(f"## 卷 {vol['no']} · {vol['name']}（{vrange(vol)}）｜{vol['line']}")
        a("")
        a(f"> **本卷回答**：{vol['question']}")
        a(f"> **卷表**：[{Path(vol['file']).name}]({body_url(vol['file'])})")
        a("")
        a("| 章 | 标题 | 知识点 | 状态 |")
        a("|---|---|---|---|")
        for no in vol["chapters"]:
            ch = data["_by_no"][no]
            pts = " ".join(ch["points"]) if ch["points"] else "—"
            if ch["status"] == "done":
                title = f"[{ch['title']}](./{fname(ch)})"
                status = "已写"
            else:
                title = ch["title"]
                status = f"待写 · [计划]({body_url(ch['plan'])})"
            a(f"| {no} | {title} | {pts} | {status} |")
        a("")

    # 知识点索引
    a('<a id="points"></a>')
    a("")
    a("## 知识点索引（108 条）")
    a("")
    a("每条知识点只有一个落点章；「另见」是引用它的收口章或应用章。")
    a("")
    a("| # | 知识点 | 一句话 | 落点章 |")
    a("|---|---|---|---|")
    owners: dict[str, list[int]] = {}
    for ch in data["chapters"]:
        for pid in ch["points"]:
            owners.setdefault(pid, []).append(ch["no"])
    for p in sorted(data["points"], key=lambda p: (GROUP_ORDER.index(p["id"][0]), int(p["id"][1:]))):
        ids = owners.get(p["id"], [])
        if ids:
            first = ids[0]
            dest = f"[第 {first} 章](./{fname(data['_by_no'][first])})" if data["_by_no"][first]["status"] == "done" \
                else f"第 {first} 章（待写）"
            if len(ids) > 1:
                dest += "（另见 " + "、".join(str(x) for x in ids[1:]) + "）"
        else:
            dest = "[附录（深水区）](./outline/41-深水区与LLM-Wiki.md)"
        a(f"| {p['id']} | {p['name']} | {p['gloss']} | {dest} |")
    a("")

    # 文件名对照
    a('<a id="files"></a>')
    a("")
    a("## 文件名与章号对照")
    a("")
    a("文件名 = 章号 + 章节标题（空格与引号去掉，`：，、` 统一换成 `-`）。改标题时同步改文件名，"
      "`python docs/check_nav.py` 会查这一条。")
    a("")
    a("| 文件 | 章 | 标题 |")
    a("|---|---|---|")
    for ch in done:
        a(f"| [{fname(ch)}](./{fname(ch)}) | {ch['no']} | {ch['title']} |")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------- 命令

def write_index(data: dict, dry: bool) -> bool:
    path = ROOT / "INDEX.md"
    text = render_index(data)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == text:
        print("INDEX.md 无变化")
        return False
    if not dry:
        path.write_text(text, encoding="utf-8", newline="\n")
    print(("将更新" if dry else "已更新") + " INDEX.md")
    return True


def build(dry: bool) -> int:
    data = load()
    changed = 0
    for ch in data["chapters"]:
        if ch["status"] != "done":
            continue
        path = ROOT / fname(ch)
        if not path.exists():
            print(f"缺少文件：{path.name}（章号 {ch['no']}）")
            return 1
        text = path.read_text(encoding="utf-8")
        new = patch_chapter(text, ch, data)
        if new != text.replace("\r\n", "\n"):
            if not dry:
                path.write_text(new, encoding="utf-8", newline="\n")
            print(("将改写" if dry else "已改写") + f" {path.name}")
            changed += 1
    write_index(data, dry)
    print(f"章节改动 {changed} 个")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "build"
    dry = "--dry" in argv
    if cmd == "index":
        write_index(load(), dry)
        return 0
    if cmd == "build":
        return build(dry)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
