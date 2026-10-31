"""把一张图的 A4 清单打印出来：字段、owner、reducer、节点读写、边、计数。

不联网。清单与图定义同源（都从 three_node_trace.build() 取），所以它不会与图不同步。
这张表就是第 48 章说的"A4 判据"的可执行版本。

运行：python code/forms/graph_engineering/spec_report.py
"""

from __future__ import annotations

from three_node_trace import build


def reducer_name(fn) -> str:
    return getattr(fn, "__name__", "overwrite")


def main() -> None:
    g = build()

    print("=== 1. 状态字段与 owner ===")
    print(f"    {'字段':<10}{'owner':<8}{'reducer':<10}")
    for f in g.fields.values():
        print(f"    {f.name:<10}{f.owner:<8}{reducer_name(f.reducer):<10}")

    print()
    print("=== 2. 节点读写 ===")
    print(f"    {'节点':<8}{'读':<32}{'写（按 owner 反推）'}")
    for n in g.nodes.values():
        owned = [f.name for f in g.fields.values() if f.owner == n.name]
        print(f"    {n.name:<8}{','.join(n.reads) or '-':<32}{','.join(owned) or '-'}")

    print()
    print("=== 3. 边 ===")
    for src, cond, dst in g.edges:
        label = "无条件" if cond is None else "条件"
        back = "（回边）" if (src, dst) in g.back_pairs else ""
        print(f"    {src:<8}--{label}--> {dst}{back}")

    print()
    print("=== 4. 三个数 ===")
    print(f"    节点数={len(g.nodes)}  边数={len(g.edges)}  字段数={len(g.fields)}  "
          f"回边上限={g.max_back_edges}")

    print()
    print("=== 5. 一致性检查 ===")
    problems = 0
    for f in g.fields.values():
        if f.owner not in g.nodes:
            print(f"    字段 {f.name} 的 owner={f.owner} 不是一个节点")
            problems += 1
        for n in g.nodes.values():
            if f.owner == n.name and f.name not in n.reads and n.reads:
                print(f"    注意：{n.name} 拥有 {f.name} 但没声明读它")
    print(f"    问题数={problems}")


if __name__ == "__main__":
    main()
