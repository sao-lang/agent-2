"""反例：三步任务画成五节点图，token 上升、成功率不变。

不联网。同一份任务、同一个正确结果，两种实现：
  链：三个函数顺序调用，每个只拿到它需要的参数
  图：五个节点，每个节点读一份状态快照（快照里带着已经用过的字段）

结果正确性按输出比对，两者都正确 —— 这正是反例要证明的：多出来的钱没有买到成功率。

运行：python code/forms/graph_engineering/graph_too_much.py
"""

from __future__ import annotations

import json

from graph_core import Field, Graph, Node, overwrite

CONFIG = {"host": "10.0.0.7", "port_base": 8000, "replicas": 3}
TASK = "读配置，算出第三个副本的端口，写一句结论"
EXPECTED = "副本 3 的端口是 8002"


def tokens_of(obj) -> int:
    return int(len(json.dumps(obj, ensure_ascii=False)) * 0.6)


# ---------- 链：三步 ----------

def chain() -> tuple[str, int, int]:
    calls = 0
    tokens = 0

    tokens += tokens_of(CONFIG)
    host, base, replicas = CONFIG["host"], CONFIG["port_base"], CONFIG["replicas"]
    calls += 1

    port = base + replicas - 1
    tokens += tokens_of({"replicas": replicas, "base": base})
    calls += 1

    text = f"副本 {replicas} 的端口是 {port}"
    tokens += tokens_of({"host": host, "port": port})
    calls += 1
    return text, calls, tokens


# ---------- 图：五节点 ----------

def load(snapshot) -> dict:
    return {"raw": dict(CONFIG)}


def parse(snapshot) -> dict:
    raw = snapshot["raw"]
    return {"parsed": {"base": raw["port_base"], "n": raw["replicas"], "host": raw["host"]}}


def compute(snapshot) -> dict:
    p = snapshot["parsed"]
    return {"result": {"port": p["base"] + p["n"] - 1, "n": p["n"]}}


def check(snapshot) -> dict:
    ok = 1024 <= snapshot["result"]["port"] <= 65535
    return {"checked": ok}


def write(snapshot) -> dict:
    r = snapshot["result"]
    return {"answer": f"副本 {r['n']} 的端口是 {r['port']}"}


def graph_run() -> tuple[str, int, int]:
    fields = [
        Field("raw", owner="load"),
        Field("parsed", owner="parse"),
        Field("result", owner="compute"),
        Field("checked", owner="check"),
        Field("answer", owner="write"),
    ]
    nodes = [
        Node("load", reads=("task",), fn=load),
        Node("parse", reads=("raw",), fn=parse),
        Node("compute", reads=("parsed",), fn=compute),
        Node("check", reads=("result",), fn=check),
        Node("write", reads=("result", "checked"), fn=write),
    ]
    edges = [("load", None, "parse"), ("parse", None, "compute"),
             ("compute", None, "check"), ("check", None, "write"), ("write", None, "END")]
    g = Graph(fields, nodes, edges, start="load", max_nodes=10)
    r = g.run({"task": TASK, "raw": {}, "parsed": {}, "result": {}, "checked": False, "answer": ""})
    return r.state["answer"], len(r.rows), r.tokens


def main() -> None:
    chain_answer, chain_calls, chain_tokens = chain()
    graph_answer, graph_calls, graph_tokens = graph_run()

    print("=== 1. 两种实现 ===")
    print(f"    链： {chain_calls} 次调用  {chain_tokens:>4} tokens  "
          f"输出={'正确' if chain_answer == EXPECTED else '错'}")
    print(f"    图： {graph_calls} 次调用  {graph_tokens:>4} tokens  "
          f"输出={'正确' if graph_answer == EXPECTED else '错'}")
    print(f"    token 上升 {(graph_tokens / chain_tokens - 1) * 100:.0f}%，"
          f"成功率变化 0（两者都正确）")

    print()
    print("=== 2. 多出来的 token 花在哪 ===")
    print(f"    链的输入是三个小对象：{tokens_of(CONFIG)} + "
          f"{tokens_of({'replicas': 3, 'base': 8000})} + {tokens_of({'host': '10.0.0.7', 'port': 8002})}")
    print("    图的每个节点都拿到一份快照，快照里包含它并不需要的字段")
    print("    load 的 reads 里还有 task（整句话），parse 之后的节点带着 raw 的副本")

    print()
    print("=== 3. 这张图买到了什么 ===")
    print("    每个节点单独可重跑：compute 挂了，能从 parse 的产物重跑")
    print("    每个节点的读写有声明：owner 检查能挡住写错字段")
    print("    这两样在'三步、两个中间值、一个人写'的规模上用不到")
    print("    判据不是'图更清晰'，是'是否需要让某个节点单独重跑或并行'（5.1）")


if __name__ == "__main__":
    main()
