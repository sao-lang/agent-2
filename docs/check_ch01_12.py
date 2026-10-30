"""前 12 章的机械检查。

用法：python docs/check_ch01_12.py

检查项：章标题与四行元信息、`这一章建立的 N 件事`、`下一章`、
第 13 章以后的裸章号引用、主线禁词、中文字符数、标题长度。
它只做机械判定；内容对不对仍然要人读。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "docs"))
from gen_book import fname  # noqa: E402

_DATA = json.loads((ROOT / "book.json").read_text(encoding="utf-8"))
CHAPTERS = [fname(c) for c in _DATA["chapters"] if c["status"] == "done" and c["no"] <= 12]

BANNED_MAIN = ["harness", "插点", "契约", "组件封装"]
BANNED_LC = ["harness", "插点", "契约"]


def prose_of(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"^\|.*$", "", text, flags=re.M)


def check(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    prose = prose_of(text)
    problems = []

    if not re.match(r"# 第 \d+ 章", text):
        problems.append("缺章标题")
    for key in ("知识点", "本章回答", "示例目录", "读完应当能回答"):
        if f"> **{key}" not in text:
            problems.append(f"缺元信息：{key}")
    if not re.search(r"## 这一章建立的 \d+ 件事", text):
        problems.append("缺『这一章建立的 N 件事』")
    if "## 下一章" not in text:
        problems.append("缺『下一章』")

    allowed_next = {13} if path.startswith("12") else set()
    high = {m.group(0) for m in re.finditer(r"第\s*(\d+)\s*章", prose)
            if int(m.group(1)) > 12 and int(m.group(1)) not in allowed_next}
    if high:
        problems.append("第 13 章以后的裸章号引用：" + "、".join(sorted(high)))

    banned = [] if path.startswith("00") else (BANNED_LC if path[:2] >= "09" else BANNED_MAIN)
    for word in banned:
        if word in prose:
            problems.append(f"主线禁词：{word}")

    count = len(re.findall(r"[\u4e00-\u9fff]", prose))
    if count < 7000 and not path.startswith("00"):
        problems.append(f"篇幅偏短（{count} 字）")

    for heading in re.findall(r"^#{2,3} (.+)$", text, flags=re.M):
        if len(re.findall(r"[\u4e00-\u9fff]", heading)) > 12:
            problems.append(f"标题超 12 字：{heading}")

    return count, problems


def main():
    failed = False
    for path in CHAPTERS:
        try:
            count, problems = check(path)
        except FileNotFoundError:
            print(f"缺失  {path}")
            failed = True
            continue
        if problems:
            failed = True
            print(f"{path}：{count} 字 | " + "；".join(problems))
        else:
            print(f"{path}：{count} 字 | OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
