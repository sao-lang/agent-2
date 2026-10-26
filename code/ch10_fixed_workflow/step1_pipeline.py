"""第 10 章 · 固定工作流的代码骨架：平台上连的四个方块，运行时是什么。

运行：
    python code/ch10_fixed_workflow/step1_pipeline.py

这一级不讲"怎么做更好的 Agent"，只做一件事：
把 Coze / Dify 画布上的四个节点，还原成四次函数调用 + 一次字符串拼接。

看清这件事之后，10.3 讲的"界面上看不见的三类状态"才有落点。
"""
from __future__ import annotations

from dataclasses import dataclass, field

DOCS = {
    "退货": "签收后 7 天内可申请无理由退货，商品需保持完好。",
    "换货": "签收后 15 天内出现质量问题可申请换新，需检测确认。",
}


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


@dataclass
class Ledger:
    """节点级计量：每个节点的耗时与 token 各记一笔（画布上通常只有总数）。"""

    calls: int = 0
    tokens: int = 0
    nodes: dict[str, dict[str, int]] = field(default_factory=dict)

    def call(self, node: str, prompt: str, out_tokens: int, ms: int = 0) -> None:
        self.calls += 1
        used = est_tokens(prompt) + out_tokens
        self.tokens += used
        slot = self.nodes.setdefault(node, {"calls": 0, "tokens": 0, "ms": 0})
        slot["calls"] += 1
        slot["tokens"] += used
        slot["ms"] += ms


# ---------------------------------------------------------------- 四个节点

def rewrite(question: str, ledger: Ledger) -> str:
    """节点 1：查询改写。固定工作流里它是一次模型调用，输入输出都固定。"""
    ledger.call("改写", "把口语问题改写成检索关键词：" + question, out_tokens=20, ms=180)
    return " ".join(question.replace("能退吗", "退货").replace("咋办", "流程").split())


def search(query: str, ledger: Ledger) -> list[str]:
    """节点 2：检索。注意它不调模型，所以画布上这个方块不产生 token。"""
    hits = [text for key, text in DOCS.items() if key in query]
    slot = ledger.nodes.setdefault("检索", {"calls": 0, "tokens": 0, "ms": 0})
    slot["calls"] += 1
    slot["ms"] += 40
    return hits


def generate(question: str, hits: list[str], ledger: Ledger) -> str:
    """节点 3：生成。上下文是拼出来的 —— 拼多长，画布上看不见。"""
    ctx = "\n".join(f"[doc] {h}" for h in hits) or "[doc] （无）"
    prompt = f"[system] 你是一名售后客服助手，不要承诺赔偿金额。\n{ctx}\n[user] {question}"
    ledger.call("生成", prompt, out_tokens=60, ms=620)
    if not hits:
        return "抱歉，我无法回答这个问题。"
    return hits[0]


def transfer(ledger: Ledger) -> str:
    slot = ledger.nodes.setdefault("转人工", {"calls": 0, "tokens": 0, "ms": 0})
    slot["calls"] += 1
    slot["ms"] += 30
    return "正在为您转接专员。"


# ---------------------------------------------------------------- 主流程

def run(question: str, ledger: Ledger) -> dict:
    rewritten = rewrite(question, ledger)
    hits = search(rewritten, ledger)
    answer = generate(question, hits, ledger)
    if "无法回答" in answer:                                 # 条件分支：判断由你的代码做
        return {"answer": transfer(ledger), "path": ["改写", "检索", "生成", "转人工"]}
    return {"answer": answer, "path": ["改写", "检索", "生成"]}


def main() -> None:
    print("=" * 70)
    print("固定工作流：改写 → 检索 → 生成 →（条件分支）")
    print("=" * 70)

    for title, question in [
        ("命中知识库的问题", "耳机有划痕能退吗"),
        ("命中不到的问题", "你们公司总部在哪"),
    ]:
        ledger = Ledger()
        out = run(question, ledger)
        print(f"\n【{title}】")
        print(f"  实际路径：{' → '.join(out['path'])}")
        print(f"  回答：{out['answer']}")
        print(f"  模型调用：{ledger.calls} 次  token：{ledger.tokens}")

    print("\n" + "=" * 70)
    print("三类画布上看不见的状态（第二个问题逐条打印）")
    print("=" * 70)
    ledger = Ledger()
    run("你们公司总部在哪", ledger)

    print("  ① 上下文预算：拼接后的上下文长度")
    print("     （真实项目里由检索条数决定，检索变多会挤掉 system 的位置）")
    print("  ② 索引版本：")
    print("     索引元信息={'doc_count': 2, 'chunk_count': 2, 'updated_at': '2026-10-20T09:12:00'}")
    print("     → 不说出这一行，你无法回答'回答为什么还是旧的'")
    print("  ③ 节点级计量：")
    print(f"     {'节点':<8}{'调用':>5}{'token':>8}{'毫秒':>7}")
    print("     " + "-" * 30)
    for name, slot in ledger.nodes.items():
        print(f"     {name:<8}{slot['calls']:>5}{slot['tokens']:>8}{slot['ms']:>7}")

    print("\n👉 平台把「设计」可视化了（画布），没把「运行」可视化（上面三类状态）。")
    print("   前者让你一周上线，后者决定你能不能维护它。")


if __name__ == "__main__":
    main()
