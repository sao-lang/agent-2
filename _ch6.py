import re
from pathlib import Path

p = Path("06-工具调用-模型只会说-不会做.md")
t = p.read_text(encoding="utf-8")
lines = t.split("\n")

def block(a, b):
    return "\n".join(lines[a - 1:b - 1]).strip("\n")

head = block(1, 12)
intro1 = block(23, 118)
s11 = block(118, 124)
s12 = block(124, 144)
s13 = block(144, 157)
s14 = block(157, 171)
s15 = block(171, 181)
s2 = block(194, 307)
s3 = block(307, 512)
s4 = block(512, 654)
s6 = block(814, 954)
s7 = block(954, 962)
tail = block(962, len(lines) + 1)


def body(s):
    """去掉首个标题行，保留正文。"""
    return s.split("\n", 1)[1].strip("\n")


def strip_num(s):
    return re.sub(r"^### \d+\.\d+ ", "### ", s, flags=re.M)


new = "\n\n".join([
    head,
    "## 模型只生成文本\n\n" + body(intro1) + "\n\n### 模型的输入里有什么\n\n" + body(s11),
    "## 工具声明\n\n"
    + "### 工具说明就是提示词\n\n" + body(s12)
    + "\n\n### 参数声明占的 token\n\n" + body(s13)
    + "\n\n### 提示词模拟的代价\n\n" + body(s14)
    + "\n\n### 工具数量与选择\n\n" + body(s15)
    + "\n\n### 工具数组与可选动作\n\n" + body(strip_num(s2)),
    "## 响应的原文\n\n" + body(strip_num(s3)),
    "## 一次完整往返\n\n" + body(strip_num(s4)),
    "## 失败面\n\n" + body(strip_num(s6)) + "\n\n" + body(s7),
    tail,
])

p.write_text(new.rstrip("\n") + "\n", encoding="utf-8")
print(re.findall(r"(?m)^#{2,3} (.+)$", new))
