"""第 39 章产出：最小 tracer（OpenTelemetry 风格，零外部依赖）。

为什么要手写一个？
因为你要先懂 span 的层级关系，再谈"接 Langfuse"。
接平台只是把 span 导出到别处，语义这一层你不懂，接什么都没用。

设计目标：
  · 三个层级：run → step → (model_call | tool_call)
  · 每条 span 有 input / output / 属性 / 耗时 / 错误
  · 能导出成 JSONL（给 jq / pandas 分析）
  · 能按 run_id 还原完整调用树
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Span:
    name: str
    kind: str  # run | step | model_call | tool_call | retrieval
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_id: str | None = None
    run_id: str = ""
    start: float = field(default_factory=time.perf_counter)
    end: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    input: Any = None
    output: Any = None
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return ((self.end or time.perf_counter()) - self.start) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "duration_ms": round(self.duration_ms, 1),
            "ts": self.start,
            "attributes": self.attributes,
            "input": _clip(self.input),
            "output": _clip(self.output),
            "error": self.error,
        }


def _clip(v: Any, limit: int = 2000) -> Any:
    """trace 里不能存无限大的内容，否则一次运行能写出几十 MB。"""
    if v is None:
        return None
    if isinstance(v, str):
        return v if len(v) <= limit else v[:limit] + f"...<truncated {len(v)} chars>"
    try:
        s = json.dumps(v, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        s = str(v)
    if len(s) > limit:
        return s[:limit] + "...<truncated>"
    return v


class Tracer:
    """线程内够用的最小实现（不做跨线程传播，够教学用）。"""

    def __init__(self, sink: Path | str | None = None) -> None:
        self.spans: list[Span] = []
        self._stack: list[Span] = []
        self.sink = Path(sink) if sink else None
        self._last_run: str | None = None

    # ---------- 核心 API ----------

    @contextmanager
    def run(self, name: str = "run", **attrs: Any) -> Iterator[Span]:
        """一次完整的 Agent 运行 = 一个 run span。

        trace 数据在 run 结束时导出并**从内存释放**，这是生产环境的常规做法
        （长驻服务下无界增长的 trace 列表迟早会吃满内存）。
        需要查看调用树时用 inspect_last_run() 从 JSONL 读回来。
        """
        with self._span(name, "run", **attrs) as span:
            span.run_id = span.span_id  # run 自己是根
            self._last_run = span.run_id
            yield span
        self.flush()

    @contextmanager
    def step(self, name: str, **attrs: Any) -> Iterator[Span]:
        """Agent 循环里的一步（例如 plan / act / observe）。"""
        with self._span(name, "step", **attrs) as span:
            yield span

    @contextmanager
    def _span(self, name: str, kind: str, **attrs: Any) -> Iterator[Span]:
        parent = self._stack[-1] if self._stack else None
        span = Span(
            name=name,
            kind=kind,
            parent_id=parent.span_id if parent else None,
            run_id=parent.run_id if parent else "",
            attributes=attrs,
        )
        self._stack.append(span)
        try:
            yield span
        except Exception as e:  # noqa: BLE001
            span.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            span.end = time.perf_counter()
            self._stack.pop()
            self.spans.append(span)

    def model_call(self, name: str = "model_call", **attrs: Any):
        return self._span(name, "model_call", **attrs)

    def tool_call(self, name: str = "tool_call", **attrs: Any):
        return self._span(name, "tool_call", **attrs)

    def retrieval(self, name: str = "retrieval", **attrs: Any):
        return self._span(name, "retrieval", **attrs)

    # ---------- 导出与分析 ----------

    def flush(self) -> None:
        if not self.sink:
            return
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("a", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        self.spans.clear()

    # ---------- 从磁盘读回（排查时的主入口） ----------

    def load_run(self, run_id: str | None = None, path: Path | str | None = None) -> list[Span]:
        """从 JSONL 还原一次运行的所有 span。

        真实排障流程：用户报错 → 拿到 run_id → 从日志里把整条链路捞出来。
        """
        p = Path(path) if path else self.sink
        if not p or not p.exists():
            return []
        rid = run_id or self._last_run
        spans: list[Span] = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                if rid and d["run_id"] != rid:
                    continue
                spans.append(
                    Span(
                        name=d["name"],
                        kind=d["kind"],
                        span_id=d["span_id"],
                        parent_id=d["parent_id"],
                        run_id=d["run_id"],
                        start=d["ts"],
                        end=d["ts"] + d["duration_ms"] / 1000,
                        attributes=d.get("attributes") or {},
                        input=d.get("input"),
                        output=d.get("output"),
                        error=d.get("error"),
                    )
                )
        return spans

    def tree(self, run_id: str | None = None, spans: list[Span] | None = None) -> str:
        """把 span 还原成缩进树——排查问题时最有用的一屏。"""
        pool = spans if spans is not None else (self.load_run(run_id) or self.spans)
        if not pool:
            return "<empty>"
        children: dict[str | None, list[Span]] = {}
        for s in pool:
            children.setdefault(s.parent_id, []).append(s)
        lines: list[str] = []

        def walk(parent: str | None, depth: int) -> None:
            for s in sorted(children.get(parent, []), key=lambda x: x.start):
                flag = "  ❌" if s.error else ""
                lines.append(
                    f"{'  ' * depth}{s.kind:<11} {s.name:<28} {s.duration_ms:>8.1f}ms{flag}"
                )
                walk(s.span_id, depth + 1)

        walk(None, 0)
        return "\n".join(lines)

    def slowest(self, n: int = 3, spans: list[Span] | None = None) -> list[Span]:
        pool = spans if spans is not None else (self.load_run() or self.spans)
        return sorted(pool, key=lambda s: s.duration_ms, reverse=True)[:n]


@contextmanager
def traced_run(tracer: Tracer, name: str = "run", **attrs: Any) -> Iterator[Span]:
    with tracer.run(name, **attrs) as span:
        yield span
