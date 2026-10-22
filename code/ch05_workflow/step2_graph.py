"""第 5 章 · 第 2 级：把管线画成图 —— 条件分支变得可测、可画、可持久化。

运行：
    python code/ch05_workflow/step2_graph.py

新增的一个概念：**条件边（conditional edge）**。

第 1 级的 if 写在函数里，好处是简单，坏处是：
  · 流程一眼看不出来（要读代码脑补）
  · 中间状态没法保存（跑到一半崩了就全没了，第 9 章要解决）

把流程画成"节点 + 边"，这两件事就都能做。
这一级不依赖任何框架，30 行代码手写一个最小图引擎。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

COMMENT = "收到货发现屏幕有两条划痕，联系客服三次没人回，我要退款，太气人了。"


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


@dataclass
class Ledger:
    calls: int = 0
    tokens: int = 0

    def call(self, label: str, prompt: str, out_tokens: int = 100) -> None:
        self.calls += 1
        self.tokens += est_tokens(prompt) + out_tokens


# ---------------------------------------------------------------- 最小图引擎

@dataclass
class Graph:
    """节点 = 函数（状态进，状态增量出）；边 = 谁接谁；条件边 = 由纯代码选路。"""

    nodes: dict[str, Callable[[dict], dict]] = field(default_factory=dict)
    edges: dict[str, str] = field(default_factory=dict)
    branches: dict[str, tuple[Callable[[dict], str], dict[str, str]]] = field(default_factory=dict)
    entry: str = ""

    def add_node(self, name: str, fn: Callable[[dict], dict]) -> None:
        self.nodes[name] = fn

    def add_edge(self, src: str, dst: str) -> None:
        self.edges[src] = dst

    def add_conditional(self, src: str, pick: Callable[[dict], str], mapping: dict[str, str]) -> None:
        self.branches[src] = (pick, mapping)

    def run(self, state: dict, max_steps: int = 20) -> tuple[dict, list[str]]:
        cur, path = self.entry, []
        for _ in range(max_steps):
            if cur == "END":
                return state, path
            path.append(cur)
            delta = self.nodes[cur](state)
            state = {**state, **delta}                  # 状态合并：新值覆盖旧值
            if cur in self.branches:
                pick, mapping = self.branches[cur]
                cur = mapping[pick(state)]              # ← 纯代码决定，不是模型
            else:
                cur = self.edges.get(cur, "END")
        raise RuntimeError(f"超过 {max_steps} 步仍未结束（图里可能有环且没有出口）")


# ---------------------------------------------------------------- 节点

def make_nodes(m: Ledger) -> dict[str, Callable[[dict], dict]]:
    def classify(s: dict) -> dict:
        m.call("分类", "判断是否退款：" + s["comment"])
        return {
            "need_refund": "退款" in s["comment"] or "划痕" in s["comment"],
            "escalate": "三次" in s["comment"] or "气" in s["comment"],
        }

    def reason(s: dict) -> dict:
        m.call("抽理由", "抽取理由：" + s["comment"])
        return {"reason": "商品有质量瑕疵，且客服未及时响应"}

    def reply(s: dict) -> dict:
        m.call("生成回复", "生成回复")
        tail = "，并升级至专员跟进" if s.get("escalate") else ""
        return {"reply": f"已为您发起退款{tail}。"}

    def thanks(s: dict) -> dict:
        return {"reply": "感谢反馈，已记录。"}

    return {"classify": classify, "reason": reason, "reply": reply, "thanks": thanks}


def build(m: Ledger) -> Graph:
    g = Graph(entry="classify")
    for name, fn in make_nodes(m).items():
        g.add_node(name, fn)

    g.add_conditional(
        "classify",
        pick=lambda s: "refund" if s["need_refund"] else "thanks",
        mapping={"refund": "reason", "thanks": "thanks"},
    )
    g.add_edge("reason", "reply")
    g.add_edge("reply", "END")
    g.add_edge("thanks", "END")
    return g


def main() -> None:
    print("=" * 68)
    print("第 2 级：把流程画成图（条件边由纯代码决定）")
    print("=" * 68)

    for title, text in [
        ("需要退款", COMMENT),
        ("不需要退款", "快递很快，包装完好，谢谢。"),
    ]:
        m = Ledger()
        state, path = build(m).run({"comment": text})
        print(f"\n【{title}】")
        print(f"  实际路径：{' → '.join(path)} → END")
        print(f"  结果：{state.get('reply')}")
        print(f"  模型调用：{m.calls} 次  token：{m.tokens:,}")

    print("\n" + "=" * 68)
    print("为什么要画成图（而不是写在函数里）")
    print("=" * 68)
    print("  1. 流程能打印出来 —— 上面那行「实际路径」，就是运行时真实的走向")
    print("  2. 每个节点只接收 state、只返回增量 —— 想在第 3 步之后暂停/恢复，")
    print("     只要把 state 存下来就行（第 9 章）")
    print("  3. 条件边的选择函数是纯函数 —— 可以单元测试，不用调模型")
    print("\n  👉 反面：如果那个 pick 函数里塞了 llm.invoke()，你就已经在写 Agent 了，")
    print("     只是穿上了 Workflow 的衣服。")


if __name__ == "__main__":
    main()
