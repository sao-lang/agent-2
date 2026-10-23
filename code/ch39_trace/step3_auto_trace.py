"""第 39 章 · 第 3 级：不用手写父子关系（用 with 自动维护）。

运行：
    python code/ch39_trace/step3_auto_trace.py

上一级你要手动传 parent=root，代码一多就会传错。
这一级做三件事：
  · 用 with 语句自动记录开始/结束
  · 用"栈"自动推断谁是父节点
  · 异常时自动记下错误

这就是所有 tracing 库的核心实现（30 行）。
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class Span:
    name: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent_id: str | None = None
    trace_id: str = ""
    start: float = field(default_factory=time.perf_counter)
    end: float | None = None
    error: str | None = None
    attributes: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return ((self.end or time.perf_counter()) - self.start) * 1000


class Tracer:
    def __init__(self, sink: Path | str | None = None) -> None:
        self.spans: list[Span] = []
        self._stack: list[Span] = []      # ← 关键：用栈记住"我现在在谁里面"
        self.sink = Path(sink) if sink else None
        self._last_run: str | None = None

    @contextmanager
    def span(self, name: str, **attrs: object) -> Iterator[Span]:
        parent = self._stack[-1] if self._stack else None
        s = Span(
            name=name,
            parent_id=parent.span_id if parent else None,
            trace_id=parent.trace_id if parent else "",
        )
        s.attributes.update(attrs)
        if parent is None:
            s.trace_id = s.span_id         # 最外层的 span 自己就是 trace 的根
            self._last_run = s.span_id
        self._stack.append(s)
        try:
            yield s
        except Exception as e:  # noqa: BLE001
            s.error = f"{type(e).__name__}: {e}"
            raise                          # ← 记录后继续抛，不吞异常
        finally:
            s.end = time.perf_counter()
            self._stack.pop()
            self.spans.append(s)

    # ---------- 导出与回读 ----------

    def flush(self) -> None:
        """把内存里的 span 写入 JSONL，然后释放内存。

        为什么要释放？常驻服务里 spans 只增不减，跑一天就吃满内存。
        """
        if not self.sink:
            return
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("a", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
        self.spans.clear()

    def load_run(self, run_id: str | None = None) -> list[Span]:
        """从 JSONL 读回一次运行的 span（排障时的主入口）。"""
        if not self.sink or not self.sink.exists():
            return []
        rid = run_id or self._last_run
        out: list[Span] = []
        with self.sink.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                if rid and d["trace_id"] != rid:
                    continue
                out.append(Span(**d))
        return out

    def tree(self) -> str:
        children: dict[str | None, list[Span]] = {}
        for s in self.spans:
            children.setdefault(s.parent_id, []).append(s)
        lines: list[str] = []

        def walk(pid: str | None, depth: int) -> None:
            for s in sorted(children.get(pid, []), key=lambda x: x.start):
                flag = f"  ❌ {s.error}" if s.error else ""
                lines.append(f"{'  ' * depth}{s.name:<24}{s.duration_ms:>8.1f}ms{flag}")
                walk(s.span_id, depth + 1)

        walk(None, 0)
        return "\n".join(lines)


# ---------------------------------------------------------------- 使用

def demo() -> Tracer:
    tracer = Tracer()

    with tracer.span("用户请求"):
        with tracer.span("步骤1 规划"):
            time.sleep(0.02)

        with tracer.span("步骤2 执行"):
            with tracer.span("工具 查退款政策"):
                time.sleep(0.12)
            with tracer.span("工具 查订单状态"):
                time.sleep(0.05)

        with tracer.span("步骤3 生成回答"):
            time.sleep(0.08)

        # 故意让一个步骤出错，看看会怎样
        try:
            with tracer.span("步骤4 发邮件通知"):
                time.sleep(0.01)
                raise RuntimeError("上游服务 503")
        except RuntimeError:
            pass    # 业务上继续，但 trace 里留下了痕迹

    return tracer


def main() -> None:
    tracer = demo()

    print("=" * 68)
    print("一次运行的完整调用树（with 自动维护父子关系）")
    print("=" * 68)
    print(tracer.tree())

    print("\n" + "=" * 68)
    print("对比：写起来和读起来都变简单了")
    print("=" * 68)
    print("  第 2 级：Span('工具 查退款政策', parent=act)   ← 要记得传 parent")
    print("  第 3 级：with tracer.span('工具 查退款政策'):   ← 缩进即层级")
    print("\n  👉 '缩进即层级'是所有 tracing 库的设计核心。")
    print("     你之后看到 Jaeger / Langfuse / OpenTelemetry 的界面，")
    print("     看到的树，本质就是这个 parent_id 关系。")


if __name__ == "__main__":
    main()