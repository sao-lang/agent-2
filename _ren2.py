import json
import subprocess
from pathlib import Path

p = Path("docs/book.json")
data = json.loads(p.read_text(encoding="utf-8"))
renames = {2: "不实输出与上下文丢失"}
for ch in data["chapters"]:
    if ch["no"] in renames:
        old = ch["title"]
        ch["title"] = renames[ch["no"]]
        print(ch["no"], old, "->", ch["title"])
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

dst = Path("02-不实输出与上下文丢失.md")
src = Path("02-模型为什么编-为什么忘.md")
if src.exists() and not dst.exists():
    subprocess.run(["git", "mv", str(src), str(dst)], check=True)
    print("moved ->", dst)
