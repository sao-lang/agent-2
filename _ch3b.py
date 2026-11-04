import re
from pathlib import Path

p = Path("03-token-成本与上下文窗口.md")
t = p.read_text(encoding="utf-8")
assert t.count("### 3.4 一次对账的流程") == 1
t = t.replace("### 3.4 一次对账的流程", "### 一次对账的流程")
p.write_text(t, encoding="utf-8")

# 检查章末清单是否还提到已被移走的小节
i = t.index("## 这一章建立的 6 件事")
print(t[i:i + 900])
