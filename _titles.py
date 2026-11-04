"""H2 标题体检：序号、超长、问句、评价词。"""
import re
from pathlib import Path

BAD = ["为什么", "怎么", "哪", "吗", "如何", "多少", "会怎么坏", "边界", "代价", "清单", "对照", "这套", "副线", "接住", "跑飞", "唯一", "真正", "最"]

rows = []
for f in sorted(Path(".").glob("*.md")):
    m = re.match(r"^(\d{2})-", f.name)
    if not m or int(m.group(1)) > 26:
        continue
    text = f.read_text(encoding="utf-8")
    for h in re.findall(r"(?m)^## (.+)$", text):
        if re.match(r"目录|这一章建立|下一章", h):
            continue
        issues = []
        if re.match(r"^[一二三四五六七八九十]+、", h):
            issues.append("带序号")
        if len(re.findall(r"[\u4e00-\u9fff]", h)) > 12:
            issues.append("超12字")
        for w in BAD:
            if w in h:
                issues.append(f"含「{w}」")
        if issues:
            rows.append((f.name[:2], h, "；".join(issues)))

for no, h, why in rows:
    print(f"{no}  {h:36} {why}")
print("问题标题：", len(rows))
