from pathlib import Path

p = Path("docs/WRITING-SPEC.md")
t = p.read_text(encoding="utf-8")
old = "**每章散文（去掉代码块、表格、标题、章首引用块）目标 4800–6250 汉字；整章按 `check_chapters.py` 的口径 6000–6800 汉字。下限 5500，不设上限。** 这是区间目标，不是配额，也不是\"必须写满\"的指标。"
new = ("**每章散文（去掉代码块、表格、标题、章首引用块）目标 2800–4400 汉字；整章按 `check_chapters.py` 的口径 3500–4500 汉字。下限 3500，不设上限。** "
       "这是区间目标，不是配额，也不是\"必须写满\"的指标。口径来源见 `docs/REFACTOR-v13-结构.md` 第一、七、八条：目标是让零基础读者读得下去，"
       "例子与知识点保持完整，砍掉的是复述、清单、方法论段与元话语；代码与真实输出不计入篇幅，一律保留。")
assert t.count(old) == 1
t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("spec updated")
