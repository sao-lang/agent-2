"""一次运行的调用树：记什么、怎么落盘、怎么还原。

不联网。整段运行是脚本化的（模拟一个 12 步的 agent 任务），但 span 是真的
写成 JSONL、再真的从文件读回来重建的。重建出来的树用来回答三个问题：
钱花在哪、哪一步慢、哪一步失败。
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

WORK = Path("_trace_demo").resolve()
TRACE_FILE = WORK / "spans.jsonl"

# 示例单价（每百万 token），只用于演示归因口径，不是任何厂商的报价
PRICE = {"input": 1.0, "output": 4.0, "cache": 0.1}


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    kind: str                  # run / model / tool / subagent / approve
    start_ms: int              # 相对运行开始的毫秒
    end_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    status: str = "ok"

    @property
    def cost(self) -> float:
        return (self.input_tokens * PRICE["input"]
                + self.output_tokens * PRICE["output"]
                + self.cache_tokens * PRICE["cache"]) / 1_000_000

    @property
    def ms(self) -> int:
        return self.end_ms - self.start_ms


def sid() -> str:
    return uuid.uuid4().hex[:8]


def build_run() -> list[Span]:
    """造一次 12 步的运行：三次模型、两次工具、一个子 agent、一次审批等待。"""
    trace = uuid.uuid4().hex[:12]
    root = Span(trace, sid(), None, "run", "run", 0, 61_200,
                status="ok")

    step1 = Span(trace, sid(), root.span_id, "step-1 定位", "model", 0, 4_200,
                 input_tokens=9_800, output_tokens=320)
    tool1 = Span(trace, sid(), step1.span_id, "tool:read_file", "tool", 4_200, 4_260)
    step2 = Span(trace, sid(), root.span_id, "step-2 读政策", "model", 4_260, 9_100,
                 input_tokens=10_400, output_tokens=280, cache_tokens=6_000)

    sub_root = Span(trace, sid(), root.span_id, "subagent 检索", "subagent", 9_100, 22_000)
    sub_m1 = Span(trace, sid(), sub_root.span_id, "sub:改写查询", "model", 9_100, 12_000,
                  input_tokens=3_600, output_tokens=140)
    sub_tool = Span(trace, sid(), sub_m1.span_id, "tool:search", "tool", 12_000, 13_500,
                    status="ok")
    sub_m2 = Span(trace, sid(), sub_root.span_id, "sub:摘要", "model", 13_500, 22_000,
                  input_tokens=18_000, output_tokens=520)

    approve = Span(trace, sid(), root.span_id, "approve 覆写 policy.md", "approve", 22_000, 58_000)
    step3 = Span(trace, sid(), root.span_id, "step-3 写文件", "model", 58_000, 61_200,
                 input_tokens=7_200, output_tokens=180)
    tool2 = Span(trace, sid(), step3.span_id, "tool:write_file", "tool", 60_900, 61_150)

    return [root, step1, tool1, step2, sub_root, sub_m1, sub_tool, sub_m2, approve, step3, tool2]


def write_spans(spans: list[Span], path: Path) -> None:
    """一行一个 span，追加写、每条 flush：中途崩了也不丢已写的。"""
    with path.open("w", encoding="utf-8") as f:
        for s in spans:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
            f.flush()


def read_spans(path: Path) -> tuple[list[Span], int]:
    """读回来，跳过坏行（比如崩溃时写了一半的最后一行）。"""
    spans: list[Span] = []
    bad = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                spans.append(Span(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                bad += 1
    return spans, bad


def tree(spans: list[Span], root_id: str, prefix: str = "") -> list[str]:
    """按 parent_id 还原成树，同行打印令牌数与耗时。"""
    out: list[str] = []
    kids = [s for s in spans if s.parent_id == root_id]
    for i, s in enumerate(kids):
        last = i == len(kids) - 1
        mark = "└─" if last else "├─"
        tok = ""
        if s.input_tokens or s.output_tokens:
            tok = f"  in={s.input_tokens} out={s.output_tokens} cache={s.cache_tokens}"
        out.append(f"{prefix}{mark} {s.name:<22} {s.ms:>6}ms{tok}")
        out.extend(tree(spans, s.span_id, prefix + ("   " if last else "│  ")))
    return out


def depth(spans: list[Span], root_id: str) -> int:
    kids = [s for s in spans if s.parent_id == root_id]
    return 0 if not kids else 1 + max(depth(spans, s.span_id) for s in kids)


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()

    spans = build_run()
    write_spans(spans, TRACE_FILE)

    # 模拟一次不完整的落盘：最后一行只写了一半
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write('{"trace_id": "x", "span_id": "half')

    back, bad = read_spans(TRACE_FILE)
    print(f"=== 1. 落盘与读回 === 写了 {len(spans)} 条，读回 {len(back)} 条，坏行 {bad} 条")

    root = next(s for s in back if s.parent_id is None)
    print(f"  trace_id={root.trace_id}  总耗时 {root.ms}ms")
    print()
    print("=== 2. 重建出来的调用树 ===")
    print(f"  run {root.ms}ms")
    for line in tree(back, root.span_id, "  "):
        print(line)

    print()
    print("=== 3. 按类型归因 ===")
    kinds: dict[str, list[Span]] = {}
    for s in back:
        kinds.setdefault(s.kind, []).append(s)
    total_cost = sum(s.cost for s in back)
    for kind, items in sorted(kinds.items()):
        c = sum(s.cost for s in items)
        ms = sum(s.ms for s in items)
        share = c / total_cost if total_cost else 0
        print(f"  {kind:<10}{len(items):>3} 个 span  耗时 {ms:>6}ms  "
              f"成本 {c:>8.6f} 元  占比 {share:>6.1%}")

    print()
    print("=== 4. 一次调用的字段是否够用 ===")
    model = [s for s in back if s.kind == "model"]
    print(f"  model span 数：{len(model)}")
    print(f"  输入 token 合计：{sum(s.input_tokens for s in model)}")
    print(f"  输出 token 合计：{sum(s.output_tokens for s in model)}")
    print(f"  缓存命中 token：{sum(s.cache_tokens for s in model)}")
    print(f"  最慢的一步：{max(model, key=lambda s: s.ms).name} "
          f"{max(s.ms for s in model)}ms")
    print("  <- 这五个数分别回答'花了多少''贵在哪''慢在哪'")

    print()
    print("=== 5. 少一个字段会怎样：去掉 parent_id 之后 ===")
    broken = [Span(**{**asdict(s), "parent_id": None}) for s in back]
    roots = [s for s in broken if s.parent_id is None]
    print(f"  原树深度 {depth(back, root.span_id)} 层")
    print(f"  去掉 parent_id 后，{len(roots)} 条记录全都成了根：谁调用了谁无法恢复")
    print("  <- trace_id 只能回答'属于同一次运行'，嵌套关系全靠 parent_id")

    shutil.rmtree(WORK)


if __name__ == "__main__":
    main()
