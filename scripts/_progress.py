"""前 26 章进度表：中文字符、散文汉字、H2 数。"""
import re
from pathlib import Path

ROOT = Path(".")
BEFORE = {
    0: 9254, 1: 6721, 2: 6924, 3: 7284, 4: 6989, 5: 6789, 6: 7181, 7: 6560, 8: 6933,
    9: 6867, 10: 7049, 11: 7164, 12: 7190, 13: 7346, 14: 7355, 15: 7268, 16: 7032,
    17: 7115, 18: 7082, 19: 7134, 20: 6991, 21: 6956, 22: 7645, 23: 7429, 24: 7155, 25: 7578, 26: 7122,
}


def zh(s):
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def prose(text):
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    body = re.sub(r"^\|.*$", "", body, flags=re.M)
    body = re.sub(r"^#{1,6} .*$", "", body, flags=re.M)
    body = re.sub(r"^>.*$", "", body, flags=re.M)
    return zh(body)


rows = []
for f in sorted(ROOT.glob("*.md")):
    m = re.match(r"^(\d{2})-", f.name)
    if not m:
        continue
    no = int(m.group(1))
    if no > 26:
        continue
    t = f.read_text(encoding="utf-8")
    body = re.sub(r"```.*?```", "", t, flags=re.S)
    body = re.sub(r"^\|.*$", "", body, flags=re.M)
    h2 = [x for x in re.findall(r"(?m)^## (.+)$", t) if not re.match(r"目录|这一章建立|下一章", x)]
    rows.append((no, f.name, zh(body), prose(t), len(h2), BEFORE.get(no, 0)))

print(f"{'章':>3} {'文件':46} {'字数':>6} {'原字数':>6} {'降幅':>6} {'散文':>6} {'H2':>3}")
total = total_before = 0
for no, name, c, p, h, b in rows:
    total += c
    total_before += b
    drop = f"{(1 - c / b) * 100:.0f}%" if b else "-"
    print(f"{no:>3} {name[:46]:46} {c:>6} {b:>6} {drop:>6} {p:>6} {h:>3}")
print(f"\n合计 {total} / 原 {total_before} = 降 {100 * (1 - total / total_before):.0f}%")
print(f"散文超 4400 的章：{[r[0] for r in rows if r[3] > 4400]}")
print(f"字数低于 3500 的章：{[r[0] for r in rows if r[2] < 3500]}")
