"""回边超限被拦 vs 靠"模型自己停"。

不联网。同一个三节点图，verify 永远说红（模型每次都"再改一版"）。
左：有回边计数，第 3 次回边时终止，原因是 back_edge_limit。
右：没有计数，只有节点总数上限，于是它一路跑到上限，最后把红的 verdict 当成结果交出去。

运行：python code/forms/graph_engineering/back_edge_limit.py
"""

from __future__ import annotations

from graph_core import Field, Graph, Node, append, overwrite

TASK = "改到 verify 说绿为止"


def plan(snapshot) -> dict:
    return {"round": 0}


def act(snapshot) -> dict:
    return {"attempts": [f"第{snapshot['round'] + 1}版"]}


def verify(snapshot) -> dict:
    return {"verdict": "red"}            # 永远不通过：模拟"再改一版"没有终点


def build(max_back: int, max_nodes: int = 24) -> Graph:
    fields = [
        Field("round", owner="plan"),
        Field("attempts", owner="act", reducer=append),
        Field("verdict", owner="verify"),
    ]
    nodes = [
        Node("plan", reads=(), fn=plan),
        Node("act", reads=("round",), fn=act),
        Node("verify", reads=("attempts",), fn=verify),
    ]
    edges = [
        ("plan", None, "act"),
        ("act", None, "verify"),
        ("verify", lambda s: s["verdict"] == "green", "END"),
        ("verify", lambda s: s["verdict"] == "red", "act"),
    ]
    if max_back > 0:
        return Graph(fields, nodes, edges, start="plan",
                     back_pairs={("verify", "act")}, max_back_edges=max_back, max_nodes=max_nodes)
    # 不带回边计数：只靠节点总数上限兜底
    return Graph(fields, nodes, edges, start="plan", max_nodes=max_nodes)


def main() -> None:
    print("=== 1. 有回边计数（上限 2） ===")
    r = build(max_back=2).run({"round": 0, "attempts": []})
    print(f"    终止={r.reason} 回边={r.back_edges} 节点调用={len(r.rows)} "
          f"尝试次数={len(r.state['attempts'])}")
    print(f"    最后 verdict={r.state['verdict']}")
    print("    <- 停下时说明白：是回边次数用完了，不是模型说完了")

    print()
    print("=== 2. 没有回边计数，只有节点总数上限（24） ===")
    r2 = build(max_back=0, max_nodes=24).run({"round": 0, "attempts": []})
    print(f"    终止={r2.reason} 回边={r2.back_edges} 节点调用={len(r2.rows)} "
          f"尝试次数={len(r2.state['attempts'])}")
    print(f"    最后 verdict={r2.state['verdict']}")
    print("    <- 花了 24 个节点，交出的仍然是一个红的 verdict")

    print()
    print("=== 3. 两种停止的差别 ===")
    print(f"    有计数：{len(r.rows)} 个节点就停，原因可读，交给人的是'回边用完了'")
    print(f"    没计数：{len(r2.rows)} 个节点才停，原因写成 max_nodes，等于'不知道为什么停'")
    print("    回边计数器不是防死循环的补丁，它是这张图的一条退出条件")


if __name__ == "__main__":
    main()
