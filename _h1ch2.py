from pathlib import Path

p = Path("02-不实输出与上下文丢失.md")
t = p.read_text(encoding="utf-8")
old = "# 第 2 章 · 模型为什么编，为什么忘"
new = "# 第 2 章 · 不实输出与上下文丢失"
assert t.count(old) == 1
t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print(t.splitlines()[0])
