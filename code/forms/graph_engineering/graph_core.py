"""图的最小运行时：节点、条件边、状态归并、回边上限、每节点落盘。

不联网。三条硬约束在代码里强制执行，不靠约定：
  1 每个状态字段有唯一 owner，节点写别人的字段直接抛 WriteConflict
  2 条件边只读状态，拿到的是只读视图，改它直接抛 TypeError
  3 回边有计数上限，超了返回 back_edge_limit，不靠上游自己停

节点名 END 是哨兵：走到它即正常结束。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

TOKENS_PER_CHAR = 0.6


def digest(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def append(old: list | None, new: list | None) -> list:
    return list(old or []) + list(new or [])


def merge(old: dict | None, new: dict | None) -> dict:
    return {**(old or {}), **(new or {})}


def overwrite(old: Any, new: Any) -> Any:
    return new


class WriteConflict(RuntimeError):
    """一个字段被非 owner 写。"""


@dataclass(frozen=True)
class Field:
    name: str
    owner: str                       # 唯一写者（节点名）
    reducer: Callable = overwrite


@dataclass
class Node:
    name: str
    reads: tuple[str, ...]
    fn: Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass
class RunResult:
    reason: str                      # completed / dead_end / back_edge_limit / max_nodes
    state: dict[str, Any]
    rows: list[dict] = field(default_factory=list)
    tokens: int = 0
    back_edges: int = 0


class Graph:
    def __init__(self, fields: list[Field], nodes: list[Node],
                 edges: list[tuple[str, Callable[[Mapping], bool] | None, str]],
                 start: str, back_pairs: set[tuple[str, str]] | None = None,
                 max_back_edges: int = 2, max_nodes: int = 24,
                 trace: str | Path | None = None) -> None:
        self.fields = {f.name: f for f in fields}
        self.nodes = {n.name: n for n in nodes}
        self.edges = edges
        self.start = start
        self.back_pairs = back_pairs or set()
        self.max_back_edges = max_back_edges
        self.max_nodes = max_nodes
        self.trace = Path(trace) if trace else None
        if self.trace:
            self.trace.write_text("", encoding="utf-8")

    def _pick_edge(self, src: str, state: Mapping[str, Any]) -> str | None:
        for s, cond, dst in self.edges:
            if s != src:
                continue
            if cond is None or cond(state):
                return dst
        return None                             # 没有匹配的边 = 死路

    def run(self, init: dict[str, Any]) -> RunResult:
        state: dict[str, Any] = {}
        for f in self.fields.values():
            state[f.name] = f.reducer(None, init.get(f.name))
        current = self.start
        visits: Counter[str] = Counter()
        back = 0
        rows: list[dict] = []
        tokens = 0

        while True:
            if current == "END":
                return RunResult("completed", state, rows, tokens, back)
            if len(rows) >= self.max_nodes:
                return RunResult("max_nodes", state, rows, tokens, back)

            node = self.nodes[current]
            snapshot = {k: state.get(k) for k in node.reads}
            t0 = time.perf_counter()
            tokens += int(len(json.dumps(snapshot, ensure_ascii=False, default=str)) * TOKENS_PER_CHAR)
            updates = node.fn(MappingProxyType(snapshot))       # 节点拿到的也是只读视图
            ms = (time.perf_counter() - t0) * 1000

            for key, value in updates.items():
                f = self.fields[key]
                if f.owner != node.name:
                    raise WriteConflict(f"{node.name} 试图写 {key}，owner 是 {f.owner}")
                state[key] = f.reducer(state.get(key), value)

            visits[current] += 1
            rows.append({"node": current, "visit": visits[current], "reads": list(node.reads),
                         "writes": sorted(updates), "ms": round(ms, 3),
                         "state": digest(state), "tokens": tokens})
            if self.trace:
                with self.trace.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")

            nxt = self._pick_edge(current, MappingProxyType(state))
            if nxt is None:
                return RunResult("dead_end", state, rows, tokens, back)
            if (current, nxt) in self.back_pairs:
                back += 1
                if back > self.max_back_edges:
                    return RunResult("back_edge_limit", state, rows, tokens, back)
            current = nxt

    def replay(self) -> None:
        """把落盘的轨迹按节点打印，供对照。"""
        if not self.trace:
            return
        for line in self.trace.read_text("utf-8").splitlines():
            row = json.loads(line)
            reads = ",".join(row["reads"]) or "-"
            writes = ",".join(row["writes"]) or "-"
            print(f"    {row['node']:<7}第{row['visit']}次 读 {reads:<36}"
                  f"写 {writes:<28}state={row['state']}")
