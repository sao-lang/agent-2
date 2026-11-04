import json
import subprocess
from pathlib import Path

p = Path("docs/book.json")
data = json.loads(p.read_text(encoding="utf-8"))
for ch in data["chapters"]:
    if ch["no"] == 6:
        print("old:", ch["title"])
        ch["title"] = "工具调用：声明、请求与回灌"
        print("new:", ch["title"])
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

src = Path("06-工具调用-模型只会说-不会做.md")
dst = Path("06-工具调用-声明-请求与回灌.md")
if src.exists():
    subprocess.run(["git", "mv", str(src), str(dst)], check=True)
    print("moved ->", dst)

for f in ["code/knowledge/ch06_tools/langchain_bind.py", "code/knowledge/ch06_tools/scripted_chat.py"]:
    if Path(f).exists():
        subprocess.run(["git", "rm", "-q", f], check=True)
        print("removed", f)
