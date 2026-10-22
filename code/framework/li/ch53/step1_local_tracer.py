"""第 53 章 step1：不用平台也能做完可观测——自己写一个 trace 收集器（离线）。

运行：
    python code/framework/li/ch53/step1_local_tracer.py

上一章（第 52 章）的痛点：
    指标算得再准，如果"每次调用没留下数据"，你仍然只能评测那 30 条手工样本。

这一级做什么：
    ① 用第 38 章那套 span/trace 的思路，写一个 40 行的收集器
    ② 把 Agent 的一次运行完整记下来（含每个节点的输入/输出/耗时）
    ③ 用 LangChain 的 callback 机制自动挂到链上
    ④ 导出成"平台能直接吃"的格式（OTLP / LangSmith / LangFuse 都能接）

关键认知：
    **可观测性 = 数据结构（span）+ 采集点（callback）+ 导出（exporter）。**
    平台只是第三段的实现，前两段你自己必须懂。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lc"))

from _fake import scripted  # noqa: E402


@dataclass
class Span:
    """一张"记录卡"（第 38 章的定义：开始/结束/做了什么/结果）。"""

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    kind: str                      # chain / llm / tool / retriever
    start: float
    end: float = 0.0
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return round((self.end - self.start) * 1000, 1) if self.end else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "duration_ms": self.duration_ms,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "error": self.error,
        }


class LocalTracer(BaseCallbackHandler):
    """把 LangChain 的回调翻译成 span。

    LangChain 会回调这些钩子：
        on_chain_start/end/error
        on_chat_model_start  → on_llm_end
        on_tool_start/end/error
    我们要做的只有一件事：**开一个 span，结束的时候关掉它，parent 用栈来维护**。
    """

    def __init__(self) -> None:
        self.spans: list[Span] = []
        self._stack: list[str] = []          # ① 用栈维护父子关系
        self.trace_id = uuid.uuid4().hex[:16]

    # ---- 通用开/关
    def _open(self, name: str, kind: str, inputs: Any) -> str:
        sid = uuid.uuid4().hex[:8]
        parent = self._stack[-1] if self._stack else None       # ② 栈顶就是父
        self.spans.append(
            Span(self.trace_id, sid, parent, name, kind, time.perf_counter(),
                 inputs=_safe(inputs))
        )
        self._stack.append(sid)
        return sid

    def _close(self, outputs: Any = None, error: str | None = None) -> None:
        if not self._stack:
            return
        sid = self._stack.pop()                                 # ③ 出栈并打卡
        for s in reversed(self.spans):
            if s.span_id == sid:
                s.end = time.perf_counter()
                s.outputs = _safe(outputs)
                s.error = error
                break

    # ---- LangChain 钩子
    def on_chain_start(self, serialized, inputs, **kw):  # noqa: ANN001, ARG002
        self._open(kw.get("name") or "chain", "chain", inputs)

    def on_chain_end(self, outputs, **kw):  # noqa: ANN001, ARG002
        self._close(outputs)

    def on_chain_error(self, error, **kw):  # noqa: ANN001, ARG002
        self._close(None, repr(error))

    def on_chat_model_start(self, serialized, messages, **kw):  # noqa: ANN001, ARG002
        self._open(kw.get("name") or "llm", "llm", {"messages": messages})

    def on_llm_end(self, response, **kw):  # noqa: ANN001, ARG002
        text = ""
        try:
            text = response.generations[0][0].text
        except Exception:  # noqa: BLE001
            pass
        self._close({"text": text})

    def on_llm_error(self, error, **kw):  # noqa: ANN001, ARG002
        self._close(None, repr(error))

    def on_tool_start(self, serialized, input_str, **kw):  # noqa: ANN001, ARG002
        name = (serialized or {}).get("name") or kw.get("name") or "tool"
        self._open(name, "tool", {"input": input_str})

    def on_tool_end(self, output, **kw):  # noqa: ANN001, ARG002
        self._close({"output": str(output)})

    def on_tool_error(self, error, **kw):  # noqa: ANN001, ARG002
        self._close(None, repr(error))

    # ---- 导出
    def dump(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.spans]

    def to_otlp_like(self) -> dict[str, Any]:
        """导成"接近 OTLP"的形状：平台（LangSmith / LangFuse / Jaeger）都能映射。"""
        return {
            "resourceSpans": [{
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "refund-agent"}}]},
                "scopeSpans": [{
                    "scope": {"name": "local-tracer"},
                    "spans": [{
                        "traceId": s.trace_id * 2,          # OTLP 要求 32 位
                        "spanId": s.span_id,
                        "parentSpanId": s.parent_id or "",
                        "name": s.name,
                        "kind": s.kind.upper(),
                        "startTimeUnixNano": int(s.start * 1e9),
                        "endTimeUnixNano": int((s.end or s.start) * 1e9),
                        "attributes": [
                            {"key": "error", "value": {"stringValue": s.error or ""}},
                        ],
                    } for s in self.spans],
                }],
            }],
        }


def _safe(v: Any, limit: int = 120) -> dict[str, Any]:
    """输入输出可能很大/不可序列化，统一截断成字符串。"""
    try:
        s = json.dumps(v, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        s = repr(v)
    return {"preview": s[:limit]}


def main() -> None:
    tracer = LocalTracer()

    prompt = ChatPromptTemplate.from_template("用一句话解释{term}")
    chain = prompt | scripted("token 是模型切分文本的最小单位。") | StrOutputParser()

    print("=" * 78)
    print("① 一次链式调用，被自动记成了几个 span")
    print("=" * 78)
    out = chain.invoke({"term": "token"}, config={"callbacks": [tracer]})
    print(f"  回答 = {out!r}")
    print(f"  记录到 {len(tracer.spans)} 个 span：")
    for s in tracer.spans:
        parent = s.parent_id or "(root)"
        print(f"    {s.name:<18}{s.kind:<8}{s.duration_ms:>7.1f}ms  parent={parent}")

    print("\n" + "=" * 78)
    print("② 还原成树（这就是平台界面上那棵调用树）")
    print("=" * 78)
    by_parent: dict[str | None, list[Span]] = {}
    for s in tracer.spans:
        by_parent.setdefault(s.parent_id, []).append(s)

    def walk(pid: str | None, depth: int = 0) -> None:
        for s in by_parent.get(pid, []):
            print("    " + "  " * depth + f"{s.name}  [{s.kind}]  {s.duration_ms}ms")
            walk(s.span_id, depth + 1)

    walk(None)

    print("\n" + "=" * 78)
    print("③ 导出：平台能直接吃的形状")
    print("=" * 78)
    otlp = tracer.to_otlp_like()
    spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    print(f"  OTLP-like 导出：{len(spans)} 个 span")
    print(f"  第一条：{json.dumps(spans[0], ensure_ascii=False)[:150]}…")
    print("  → OTLP 是业界通用形状；LangSmith / LangFuse 各有自己的 API，但字段能一一对应")

    print("\n" + "=" * 78)
    print("④ 一个失败案例：错误也被记下来了")
    print("=" * 78)

    def boom(_x: str) -> str:
        raise ValueError("工具炸了")

    from langchain_core.runnables import RunnableLambda

    bad = RunnableLambda(boom)
    t2 = LocalTracer()
    try:
        bad.invoke("x", config={"callbacks": [t2]})
    except ValueError:
        pass
    for s in t2.spans:
        print(f"  {s.name:<18}{s.kind:<8} error={s.error}")
    print("  → 错误必须进 span。否则你只知道'失败了'，不知道'哪一步失败'。")

    print("\n" + "=" * 78)
    print("⑤ 平台到底替你做了什么")
    print("=" * 78)
    print("""  你写的这 80 行 = 平台做的三件事：
    1. 采集（callback 钩子 → span）        ← 你已经写了
    2. 存储（按 trace_id 索引、可查询）     ← 平台提供
    3. 展示（调用树、耗时、token 统计、过滤） ← 平台提供
  → 所以"不用平台也能做完第 38 章的事"是真的；
    平台省的是"存储 + 展示 + 多机汇总"这三件体力活。""")


if __name__ == "__main__":
    main()
