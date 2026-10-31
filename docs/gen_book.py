#!/usr/bin/env python3
"""从 book.json 生成 INDEX.md，并维护各章的章首元信息、章内目录与章末导航。

用法：
    python docs/gen_book.py index          # 只重新生成 INDEX.md
    python docs/gen_book.py build          # 生成 INDEX.md，并改写已写章节的章首/目录/章末
    python docs/gen_book.py build --dry    # 只打印将要发生的改动
    python docs/gen_book.py new 33         # 按当前标准创建第 33 章骨架（不覆盖已存在文件）

约定（改动前先读 docs/WRITING-SPEC.md 第 1.4 节）：
  * book.json 是唯一事实源：卷、章、知识点、状态、落点计划都在这里。
  * 文件名 = 章号 + 标题（空格与引号去掉，：，、统一换成 -）。
  * 生成是幂等的：重复运行不会叠加内容。
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "docs" / "book.json"

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


def index_url(path: str) -> str:
    """docs/INDEX.md 指向仓库根目录文件的相对路径。"""
    return "../" + path


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
            f"｜[全书目录](./docs/INDEX.md#vol{vol['no']})"
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
    if prev and prev["status"] == "done":
        parts.append(f"[← 第 {prev['no']} 章 · {prev['title']}](./{fname(prev)})")
    elif prev:
        v0 = data["_vol"][prev["no"]]
        parts.append(f"第 {prev['no']} 章 · {prev['title']}（卷 {v0['no']}，待写）")
    else:
        parts.append("[全书目录](./docs/INDEX.md)")
    parts.append(f"[卷 {vol['no']} 目录](./docs/INDEX.md#vol{vol['no']})")
    nxt = data["_by_no"].get(ch["no"] + 1)
    if nxt is None:
        parts.append("[全书目录](./docs/INDEX.md)")
    elif nxt["status"] == "done":
        parts.append(f"[第 {nxt['no']} 章 · {nxt['title']} →](./{fname(nxt)})")
    else:
        v2 = data["_vol"][nxt["no"]]
        parts.append(f"第 {nxt['no']} 章 · {nxt['title']}（卷 {v2['no']}，待写）"
                     f"→ [章节计划]({body_url(nxt['plan'])})")
    return "　｜　".join(parts)


def iter_h2(lines: list[str]):
    """按顺序产出正文里的 H2（跳过围栏代码块里的示例标题）。"""
    fence = None
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if line.startswith("## ") and not line.startswith("### "):
            yield line[3:].strip()


def heading_slug(title: str) -> str:
    """GitHub / VS Code 预览使用的标题 id：小写、去标点、空格变连字符。"""
    title = re.sub(r"`([^`]*)`", r"\1", title)
    title = re.sub(r"<[^>]+>", "", title)
    title = title.strip().lower()
    kept = [
        c for c in title
        if c.isalnum() or c in " -_" or unicodedata.category(c).startswith("M")
    ]
    return "".join(kept).strip().replace(" ", "-") or "section"


def toc_block(lines: list[str]) -> list[str]:
    entries = []
    seen: dict[str, int] = {}
    for title in iter_h2(lines):
        if title in ("目录", "下一章"):
            continue
        base = heading_slug(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        slug = base if n == 0 else f"{base}-{n}"
        entries.append(f"[{title}](#{slug})")
    if not entries:
        return []
    # 行尾反斜杠是 CommonMark 的硬换行：每项独占一行，且不需要项目符号。
    body = [entry + "\\" for entry in entries[:-1]] + [entries[-1]]
    return ["## 目录", "", *body]


def apply_toc(lines: list[str]) -> list[str]:
    """在章首分隔线之后维护 `## 目录`；重复运行只替换旧块。"""
    h1 = next(k for k, line in enumerate(lines) if line.startswith("# "))
    sep = next((k for k in range(h1 + 1, len(lines)) if lines[k].strip() == "---"), None)
    if sep is None:
        return lines
    toc = toc_block(lines)
    if not toc:
        return lines

    start = next(
        (k for k in range(sep + 1, len(lines)) if lines[k].strip() == "## 目录"),
        None,
    )
    if start is not None:
        # 只替换「## 目录 + 空行 + 目录正文」，保留目录之后的导语/正文。
        # 兼容旧版列表目录：整段列表一起删掉。
        end = start + 1
        while end < len(lines) and not lines[end].strip():
            end += 1
        while end < len(lines) and (
            lines[end].startswith("- [") or lines[end].startswith("[")
        ):
            end += 1
        while end < len(lines) and not lines[end].strip():
            end += 1
        return lines[:start] + toc + [""] + lines[end:]

    at = sep + 1
    while at < len(lines) and not lines[at].strip():
        at += 1
    return lines[:at] + toc + [""] + lines[at:]


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

    def is_nav(line: str) -> bool:
        return "｜" in line and ("目录" in line or "章" in line)

    while tail and is_nav(tail[-1]):
        tail.pop()
        while tail and not tail[-1].strip():
            tail.pop()
        if tail and tail[-1].strip() == "---":
            tail.pop()
            while tail and not tail[-1].strip():
                tail.pop()
    tail += ["", "---", "", nav_line(ch, data), ""]
    lines = lines[:k + 1] + tail
    lines = apply_toc(lines)
    return "\n".join(lines)


# ---------------------------------------------------------------- INDEX.md

def num_ranges(nums: list[int]) -> str:
    """连续段压缩：0,1,2,5 -> "0–2、5"。"""
    if not nums:
        return "—"
    nums = sorted(nums)
    parts: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}–{prev}")
    return "、".join(parts)


def render_index(data: dict) -> str:
    done = [c for c in data["chapters"] if c["status"] == "done"]
    pending = [c["no"] for c in data["chapters"] if c["status"] != "done"]
    out: list[str] = []
    a = out.append

    a(f"# 《{data['title']}》全书目录")
    a("")
    a(f"> {len(data['volumes'])} 卷、{data['chapters_total']} 章"
      f"（第 0–{data['chapters_total'] - 1} 章）、{data['points_total']} 条知识点。"
      f"**已写 {len(done)} 章（{num_ranges([c['no'] for c in done])}）**，"
      f"待写 {num_ranges(pending)}。")
    a(">")
    a("> 本文件由 `python docs/gen_book.py index` 从 [`book.json`](./book.json) 生成，不要手改。")
    a("> 章节结构见 [OUTLINE.md](./OUTLINE.md)，知识点定义见 [outline/](../outline/)，"
      "写法见 [WRITING-SPEC.md](./WRITING-SPEC.md)。")
    a("")
    a("## 怎么用这份目录")
    a("")
    a("- 顺序读：从[第 0 章](../00-agent的差别.md)开始；每章末尾都有「上一章 ｜ 卷目录 ｜ 下一章」。")
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
        a(f"> **卷表**：[{Path(vol['file']).name}]({index_url(vol['file'])})")
        a("")
        a("| 章 | 标题 | 知识点 | 状态 |")
        a("|---|---|---|---|")
        for no in vol["chapters"]:
            ch = data["_by_no"][no]
            pts = " ".join(ch["points"]) if ch["points"] else "—"
            if ch["status"] == "done":
                title = f"[{ch['title']}](../{fname(ch)})"
                status = "已写"
            else:
                title = ch["title"]
                status = f"待写 · [计划]({index_url(ch['plan'])})"
            a(f"| {no} | {title} | {pts} | {status} |")
        a("")

    # 知识点索引
    a('<a id="points"></a>')
    a("")
    a(f"## 知识点索引（{data['points_total']} 条）")
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
            dest = f"[第 {first} 章](../{fname(data['_by_no'][first])})" if data["_by_no"][first]["status"] == "done" \
                else f"第 {first} 章（待写）"
            if len(ids) > 1:
                dest += "（另见 " + "、".join(str(x) for x in ids[1:]) + "）"
        else:
            dest = "[附录（深水区）](../outline/41-深水区与LLM-Wiki.md)"
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
        a(f"| [{fname(ch)}](../{fname(ch)}) | {ch['no']} | {ch['title']} |")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------- 命令

def write_index(data: dict, dry: bool) -> bool:
    path = ROOT / "docs" / "INDEX.md"
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


def new_chapter(no: int, data: dict) -> int:
    """按当前章首/目录/章末标准创建一个空章骨架，不覆盖已存在文件。"""
    ch = data["_by_no"].get(no)
    if ch is None:
        print(f"book.json 里没有第 {no} 章")
        return 1
    path = ROOT / fname(ch)
    if path.exists():
        print(f"已存在：{path.name}；不覆盖")
        return 1
    skeleton = "\n".join([
        f"# 第 {no} 章 · {ch['title']}",
        "",
        f"> {vol_line(ch, data)}",
        ">",
        f"> - {point_line(ch, data)}",
        "> - **本章回答**：TODO",
        f"> - **示例目录**：`code/knowledge/ch{no:02}_TODO/`",
        "> - **读完应当能回答**：TODO",
        "",
        "---",
        "",
        "## 一、第一节标题",
        "",
        "正文。",
        "",
        "## 这一章建立的 N 件事",
        "",
        "## 下一章",
        "",
    ])
    path.write_text(patch_chapter(skeleton, ch, data), encoding="utf-8", newline="\n")
    print(f"已创建 {path.name}；替换 TODO 与占位标题后再跑 build")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "build"
    dry = "--dry" in argv
    if cmd == "index":
        write_index(load(), dry)
        return 0
    if cmd == "build":
        return build(dry)
    if cmd == "new":
        if len(argv) < 3:
            print("用法：python docs/gen_book.py new <章号>")
            return 2
        try:
            no = int(argv[2])
        except ValueError:
            print(f"章号必须是整数：{argv[2]}")
            return 2
        return new_chapter(no, load())
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
