"""第 6 章：按零基础口径删节。"""
import re
from pathlib import Path

p = Path("06-工具调用-模型只会说-不会做.md")
lines = p.read_text(encoding="utf-8").split("\n")

heads = [(i, l) for i, l in enumerate(lines) if re.match(r"^#{1,3} ", l)]

DROP = [
    "### 参数声明占的 token",
    "### 提示词模拟的代价",
    "### 工具数量与选择",
    "### 工具数量的两条约束",
    "### 第二次请求多了什么",
    "### 这一步为什么不是循环",
    "### 重放与去重",
    "### 四个观察点",
]

ranges = []
for title in DROP:
    start = next(i for i, l in heads if l == title)
    after = [i for i, _ in heads if i > start]
    end = after[0] if after else len(lines)
    ranges.append((start, end))

for start, end in sorted(ranges, reverse=True):
    del lines[start:end]

t = "\n".join(lines)
t = t.replace("# 第 6 章 · 工具调用：模型只会说，不会做", "# 第 6 章 · 工具调用：声明、请求与回灌", 1)

old7 = ("7. 六种坏法全部发生在调用方这一段：参数解析、工具名校验、执行分支、回灌格式、结果配对、副作用重放。"
        "框架接管了 schema 生成、请求编码、响应解析、消息对象四件事，其余仍在调用方。"
        "第一层判断必须是 `finish_reason`，不是 `content` 是否为空。")
new7 = ("7. 坏法全部发生在调用方这一段：参数解析、工具名校验、执行分支、回灌格式、结果配对。"
        "第一层判断必须是 `finish_reason`，不是 `content` 是否为空。")
if old7 in t:
    t = t.replace(old7, new7)
else:
    print("警告：第 7 条未命中")

p.write_text(t, encoding="utf-8")
print([x for x in re.findall(r"(?m)^## (.+)$", t)])
