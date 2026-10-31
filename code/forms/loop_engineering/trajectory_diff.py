"""轨迹的字段与可 diff 性：两次运行差在哪一步，用哈希答，不用读日志。

不联网。同一个任务跑三次：A 按修改时间取片段，B 按文件名取片段，
C 把观测排序后归一化（内容序）。A 与 B 的差别是真的（行为分叉），
A 与 C 的差别是假的（只是顺序噪声）。

运行：python code/forms/loop_engineering/trajectory_diff.py
"""

from __future__ import annotations

import json
from pathlib import Path

from loop_core import Action, Limits, Loop

TASK = "从三份日志里找出错误并写一句结论"
SNIPPETS = ["log_c: 10:02 ERROR timeout", "log_a: 10:01 ERROR 401", "log_b: 10:03 WARN retry"]


def order(kind: str) -> list[str]:
    if kind == "mtime":
        return [SNIPPETS[1], SNIPPETS[0], SNIPPETS[2]]      # log_a, log_c, log_b
    if kind == "name":
        return [SNIPPETS[2], SNIPPETS[1], SNIPPETS[0]]      # log_b, log_a, log_c
    return sorted(SNIPPETS)               # canonical：内容序，与文件先后无关


def make_policy_act(kind: str):
    def policy(lp: Loop, obs: str) -> Action | None:
        if "hits" not in lp.state:
            return Action("search", "logs", "ERROR|WARN")
        if lp.state.get("read") is None:
            return Action("read", lp.state["hits"][0].split(":")[0])
        return Action("write", "conclusion", f"先查 {lp.state['read']}")

    def act(lp: Loop, action: Action) -> str:
        if action.kind == "search":
            hits = order(kind)
            lp.state["hits"] = hits
            return "命中 3 条，顺序：" + " | ".join(hits)
        if action.kind == "read":
            lp.state["read"] = action.target
            return f"已读 {action.target} 的 40 行"
        return "已写结论"
    return policy, act


def run(kind: str) -> list[dict]:
    policy, act = make_policy_act(kind)
    lp = Loop(f"trace-{kind}", policy, act, Limits(max_steps=5))
    lp.run(TASK)
    return lp.records


def write_jsonl(name: str, rows: list[dict]) -> Path:
    out = Path(__file__).with_name("_work_trace")
    out.mkdir(exist_ok=True)
    path = out / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def first_diff(a: list[dict], b: list[dict], field: str) -> int | None:
    for i in range(min(len(a), len(b))):
        if a[i][field] != b[i][field]:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def report(name_a: str, a: list[dict], name_b: str, b: list[dict]) -> None:
    obs_i = first_diff(a, b, "observation_hash")
    act_i = first_diff(a, b, "action_hash")
    print(f"  {name_a} vs {name_b}：")
    if obs_i is None:
        print("    全部一致")
        return
    print(f"    第一个观测不同的步：step={a[obs_i]['step']} "
          f"{a[obs_i]['observation_hash']} / {b[obs_i]['observation_hash']}")
    if act_i is None:
        print("    动作序列完全一致 -> 观测噪声，不是行为分叉")
    else:
        print(f"    第一个动作不同的步：step={a[act_i]['step']} "
              f"{a[act_i]['action']} / {b[act_i]['action']}")
        print(f"    从这一步起两次运行不可比：{name_a} 与 {name_b} 走了不同分支")


def main() -> None:
    runs = {k: run(k) for k in ("mtime", "name", "canonical")}

    print("=== 1. 一份轨迹的字段（A 的前两行原文） ===")
    path = write_jsonl("run_a", runs["mtime"])
    for line in path.read_text("utf-8").splitlines()[:2]:
        print("    " + line)

    print()
    print("=== 2. A 与 B（取片段的排序不同） ===")
    report("A", runs["mtime"], "B", runs["name"])

    print()
    print("=== 3. A 与 C（观测归一化之后） ===")
    report("A", runs["mtime"], "C", runs["canonical"])

    print()
    print("=== 4. 判断可 diff 的口径 ===")
    print("    观测哈希不同 -> 先看动作是否相同：相同则是噪声")
    print("    动作哈希不同 -> 行为真的分叉，从这里往后不能直接对比结果")
    print("    要比较两次运行，先归一化观测（排序 / 去时间戳 / 去绝对路径 / 去 run_id）")


if __name__ == "__main__":
    main()
