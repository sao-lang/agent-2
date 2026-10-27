"""把一批校验失败聚成一张表：先看哪类错最多，再决定改什么。

运行：python code/knowledge/ch05_pydantic/error_stats.py
"""

from collections import Counter

from pydantic import BaseModel, Field, ValidationError


class Verdict(BaseModel):
    eligible: bool
    reason: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0, le=1)


BATCH = [
    {"eligible": "true", "reason": "未拆封", "confidence": 0.8},
    {"eligible": True, "confidence": 0.9},
    {"eligible": False, "confidence": 0.9},
    {"eligible": True, "reason": "", "confidence": 1.2},
    {"eligible": True, "reason": "未拆封", "confidence": 0.7},
    {"eligible": None, "reason": "信息不足", "confidence": 0.4},
    {"eligible": True, "reason": "", "confidence": 0.5},
    {"eligible": True, "reason": "未拆封", "confidence": -0.1},
    {"eligible": True, "reason": None, "confidence": 0.8},
]

counter = Counter()
for i, payload in enumerate(BATCH):
    try:
        Verdict.model_validate(payload)
    except ValidationError as exc:
        for err in exc.errors():
            counter[(err["loc"][0], err["msg"])] += 1
    else:
        print(f"第 {i} 条通过")

print("\n失败类型统计：")
for (field, msg), n in counter.most_common():
    print(f"  {n} 次  {field}: {msg}")
