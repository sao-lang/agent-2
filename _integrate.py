"""批次收尾：改章名、改 H1、改名文件。正文由各分组改完后统一执行。"""
import json
import subprocess
from pathlib import Path

RENAME = {
    23: ("反思：为什么自己评自己没用", "反思：外部裁判与修复粒度"),
    24: ("状态：循环记住什么", "状态：循环要记住的字段"),
}

p = Path("docs/book.json")
data = json.loads(p.read_text(encoding="utf-8"))
for ch in data["chapters"]:
    if ch["no"] in RENAME:
        ch["title"] = RENAME[ch["no"]][1]
        print(f"book.json 第 {ch['no']} 章 -> {ch['title']}")
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fname(no, title):
    t = title
    for a in (" ", "\u3000", "“", "”", "`", '"'):
        t = t.replace(a, "")
    for a in ("：", "，", "、"):
        t = t.replace(a, "-")
    return f"{no:02d}-{t}.md"


for no, (old_title, new_title) in RENAME.items():
    src = Path(fname(no, old_title))
    dst = Path(fname(no, new_title))
    if src.exists() and not dst.exists():
        subprocess.run(["git", "mv", str(src), str(dst)], check=True)
        print("moved:", src, "->", dst)
        text = dst.read_text(encoding="utf-8")
        old_h1 = f"# 第 {no} 章 · {old_title}"
        new_h1 = f"# 第 {no} 章 · {new_title}"
        if old_h1 in text:
            dst.write_text(text.replace(old_h1, new_h1, 1), encoding="utf-8")
            print("H1 fixed:", new_h1)
    elif dst.exists():
        print("已存在，跳过:", dst)
    else:
        print("找不到源文件:", src)
