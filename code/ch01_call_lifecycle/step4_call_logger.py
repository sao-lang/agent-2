"""第 1 章 step4：调用记录器（离线可运行）。

运行：
    python code/ch01_call_lifecycle/step4_call_logger.py

演示按字段记录一次调用，并判断结果是否可直接使用。
写入位置默认为系统临时目录，不污染仓库。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class CallRecord:
    request_id: str
    model: str
    messages: list[dict]
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """本次调用结果是否可以交给业务使用。"""
        return self.error is None and self.finish_reason == "stop"


class CallLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, rec: CallRecord) -> None:
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def replay(self) -> list[CallRecord]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(CallRecord(**json.loads(line)))
        return out


class Timer:
    """用 with 语句测量一段代码的耗时。"""

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.elapsed_ms = int((time.perf_counter() - self.start) * 1000)


SAMPLES = [
    ("正常结束", "stop", None),
    ("被 max_tokens 截断", "length", None),
    ("请求失败", "", "ConnectionError"),
]


def main() -> None:
    path = Path(tempfile.gettempdir()) / "ch01_calls.jsonl"
    if path.exists():
        path.unlink()
    logger = CallLogger(path)

    print("=" * 72)
    print("① 记录三次调用")
    print("=" * 72)
    print(f"  {'场景':<18}{'finish_reason':<14}{'usable':<8}{'是否交给下游'}")
    print("  " + "-" * 66)
    for name, reason, err in SAMPLES:
        with Timer() as t:
            time.sleep(0.001)
        rec = CallRecord(
            request_id=f"req-{name}",
            model="demo-model",
            messages=[{"role": "user", "content": "耳机能退吗？"}],
            finish_reason=reason,
            prompt_tokens=12,
            completion_tokens=18,
            latency_ms=t.elapsed_ms,
            error=err,
        )
        logger.record(rec)
        print(f"  {name:<18}{reason or '(空)':<14}{str(rec.usable):<8}"
              f"{'是' if rec.usable else '否，转处理'}")

    print()
    print("=" * 72)
    print("② 从文件读回")
    print("=" * 72)
    back = logger.replay()
    print(f"  共 {len(back)} 条")
    for r in back:
        print(f"  {r.request_id:<22}{r.finish_reason or '(空)':<12}"
              f"tokens={r.prompt_tokens}+{r.completion_tokens}")

    print()
    print("=" * 72)
    print("③ 结论")
    print("=" * 72)
    print("  1. usable 只看 finish_reason 与 error，不看 content 是否为空")
    print("  2. 逐行 JSON 追加写入，无需读改写")
    print("  3. 读回后可直接还原为记录对象")

    path.unlink()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
