"""校验本身的耗时：与一次模型调用比，差几个数量级。

运行：python code/knowledge/ch05_pydantic/validate_speed.py
"""

import timeit

from pydantic import BaseModel, Field


class Verdict(BaseModel):
    eligible: bool
    reason: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0, le=1)


PAYLOAD = {"eligible": True, "reason": "未拆封，符合七天无理由", "confidence": 0.83}
N = 10000

elapsed = timeit.timeit(lambda: Verdict.model_validate(PAYLOAD), number=N)
print(f"{N} 次校验耗时 {elapsed * 1000:.1f} ms，单次约 {elapsed / N * 1e6:.2f} 微秒")
