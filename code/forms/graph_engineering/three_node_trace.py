"""三节点图：plan -> act（每次处理一条）-> verify（不过就回 act）。

不联网，节点是固定剧本。这张图回答三件事：
  每个节点只读它声明的字段、只写它有 owner 的字段
  条件边只读状态，不匹配时走死路（dead_end）
  回边有计数上限（这里是 2），不靠 verify 节点自己说"算了吧"

运行：python code/forms/graph_engineering/three_node_trace.py
"""

from __future__ import annotations

from pathlib import Path

from graph_core import (Graph, Node, RunResult, append, digest, merge,
                        overwrite, Field)

TASK = "读三份日志，各写一条发现，最后校验齐全"
LOGS = {"log_a": "401 鉴权失败", "log_b": "timeout 30s", "log_c": "WARN 重试成功"}


def plan(snapshot) -> dict:
    return {"items": list(LOGS), "notes": {"planned": len(LOGS)}}


def act(snapshot) -> dict:
    items, findings = snapshot["items"], snapshot["findings"]
    done = {f.split(":")[0] for f in findings}
    missing = [i for i, it in enumerate(items) if it not in done]
    if not missing:
        return {"cursor": len(items)}
    i = missing[0]
    if i == 2 and snapshot["attempts"].count(2) == 0:
        return {"cursor": i + 1, "attempts": [2]}     # 第一次写不出来，verify 会打回
    return {"cursor": i + 1, "attempts": [i],
            "findings": [f"{items[i]}: {LOGS[items[i]]}"]}


def verify(snapshot) -> dict:
    ok = len(snapshot["findings"]) >= len(snapshot["items"])
    return {"verdict": "green" if ok else "red"}


def build(trace: Path | None = None, max_back: int = 2) -> Graph:
    fields = [
        Field("items", owner="plan", reducer=overwrite),
        Field("cursor", owner="act", reducer=overwrite),
        Field("attempts", owner="act", reducer=append),
        Field("findings", owner="act", reducer=append),
        Field("verdict", owner="verify", reducer=overwrite),
        Field("notes", owner="plan", reducer=merge),
    ]
    nodes = [
        Node("plan", reads=(), fn=plan),
        Node("act", reads=("items", "cursor", "findings", "attempts"), fn=act),
        Node("verify", reads=("items", "findings"), fn=verify),
    ]
    edges = [
        ("plan", None, "act"),
        ("act", lambda s: s["cursor"] < len(s["items"]), "act"),
        ("act", lambda s: s["cursor"] >= len(s["items"]), "verify"),
        ("verify", lambda s: s["verdict"] == "green", "END"),
        ("verify", lambda s: s["verdict"] == "red", "act"),
    ]
    return Graph(fields, nodes, edges, start="plan", back_pairs={("verify", "act")},
                 max_back_edges=max_back, max_nodes=20, trace=trace)


def main() -> None:
    trace = Path(__file__).with_name("_work_three.jsonl")
    g = build(trace=trace)
    result: RunResult = g.run({"items": [], "cursor": 0, "findings": [], "verdict": "", "notes": {}})

    print("=== 1. 执行轨迹（每节点读什么、写什么、耗时） ===")
    for row in result.rows:
        reads = ",".join(row["reads"]) or "-"
        writes = ",".join(row["writes"]) or "-"
        print(f"    {row['node']:<7}第{row['visit']}次 读 {reads:<36}"
              f"写 {writes:<28}{row['ms']:>8.3f}ms  累计tokens={row['tokens']}")

    print()
    print("=== 2. 结束状态与原因 ===")
    print(f"    终止={result.reason} 回边={result.back_edges} 节点调用={len(result.rows)} "
          f"tokens={result.tokens}")
    print(f"    findings={result.state['findings']}")
    print(f"    verdict={result.state['verdict']}  notes={result.state['notes']}")

    print()
    print("=== 3. 同一次运行落盘后的回放（逐行 JSONL） ===")
    g2 = build(trace=Path(__file__).with_name("_work_three.jsonl"))
    g2.run({"items": [], "cursor": 0, "findings": [], "verdict": "", "notes": {}})
    g2.replay()

    print()
    print("=== 4. 写别人的字段会怎样（把 findings 的 owner 写成 plan） ===")
    bad = [
        Field("items", owner="plan"),
        Field("cursor", owner="act"),
        Field("attempts", owner="act"),
        Field("findings", owner="plan"),      # 故意写错
        Field("verdict", owner="verify"),
        Field("notes", owner="plan"),
    ]
    nodes = [Node("plan", reads=(), fn=plan),
             Node("act", reads=("items", "cursor", "findings", "attempts"), fn=act),
             Node("verify", reads=("items", "findings"), fn=verify)]
    edges = [("plan", None, "act"), ("act", lambda s: True, "verify"),
             ("verify", None, "END")]
    try:
        Graph(bad, nodes, edges, start="plan").run(
            {"items": [], "cursor": 0, "attempts": [], "findings": [], "verdict": "", "notes": {}})
    except Exception as e:                       # noqa: BLE001 演示用
        print(f"    {type(e).__name__}: {e}")
    print("    <- owner 不是文档约定，是运行时检查；写错立刻炸，不会等并行汇合时才丢数据")


if __name__ == "__main__":
    main()
