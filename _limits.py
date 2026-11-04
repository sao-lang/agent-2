from pathlib import Path

# 1) check_chapters.py：下限 5500 → 3500
p = Path("docs/check_chapters.py")
t = p.read_text(encoding="utf-8")
t = t.replace("MIN_CHARS = 5500          # 目标 6000–6800（见 WRITING-SPEC 第二节与 REFACTOR-v12-精简.md）",
              "MIN_CHARS = 3500          # 目标 3500–4500（见 REFACTOR-v13-结构.md 第一、八条）")
t = t.replace("  4. 中文字符数（不含代码块与表格）不低于 5500",
              "  4. 中文字符数（不含代码块与表格）不低于 3500")
p.write_text(t, encoding="utf-8")

# 2) lint_prose.py：散文汉字区间 4800–6250 → 2800–4400
p = Path("docs/lint_prose.py")
t = p.read_text(encoding="utf-8")
old = '    ("prose_zh", "散文汉字", 4800, 6250),'
new = '    ("prose_zh", "散文汉字", 2800, 4400),'
assert t.count(old) == 1
t = t.replace(old, new)
p.write_text(t, encoding="utf-8")

print("checkers updated")
